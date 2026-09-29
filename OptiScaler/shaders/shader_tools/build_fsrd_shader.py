"""Rebuild fsrd_preprocess shaders: cso + generated header (listing prefix + byte array).

Mirrors the layout the existing precompiled headers use, so the checked-in artifacts stay
in the same shape: an `#if 0` DXIL listing for reference, then the cso bytes.
FSRDInputConv builds both the original and enabled additive variants so an edit to
their shared source cannot leave either conversion PSO with a stale artifact.
"""
import subprocess
import sys
import os
import argparse
import io
import tempfile
from fsrd_toolchain import dxc

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PRE = "OptiScaler/shaders/fsrd_preprocess/precompile"
VERIFY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_fsrd_mirrors.py")


def build(name, compiler):
    src = os.path.join(ROOT, PRE, name + ".hlsl")
    cso = os.path.join(ROOT, PRE, name + "_Shader.cso")
    asm = os.path.join(ROOT, PRE, name + ".asm")
    hdr = os.path.join(ROOT, PRE, name + "_Shader.h")

    args = [str(compiler), "-T", "cs_6_2", "-E", "CSMain", "-enable-16bit-types", "-O3",
            "-Qstrip_debug", "-Qstrip_reflect", src, "-Fo", cso, "-Fc", asm]
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        raise SystemExit("dxc failed for " + name)

    with open(asm, "r", encoding="utf-8", errors="replace") as f:
        # DXC emits a few listing lines with trailing spaces. Normalize them here so
        # regenerated checked-in headers pass git diff --check deterministically.
        listing = "\n".join(
            line.rstrip() for line in f.read().replace("\r\n", "\n").splitlines()
        )
    os.remove(asm)

    with open(cso, "rb") as f:
        data = f.read()

    with io.StringIO() as f:
        f.write("#if 0\n")
        f.write(listing)
        f.write("\n\n#endif\n\n")
        f.write("const unsigned char %s_cso[] = {\n    " % name)
        for i, b in enumerate(data):
            f.write("0x%02x" % b)
            if i < len(data) - 1:
                f.write(",")
                f.write("\n    " if (i + 1) % 12 == 0 else " ")
        f.write("\n};\n")
        header = f.getvalue().encode('utf-8')

    # Avoid truncating a header while the IDE/indexer reads it. Reproducibility
    # checks should not rewrite identical artifacts at all; changed headers are
    # published atomically, so a failed write cannot leave an incomplete array.
    existing = None
    if os.path.isfile(hdr):
        with open(hdr, 'rb') as f:
            existing = f.read()
    if existing != header:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(hdr), suffix='.tmp', delete=False) as f:
                temporary = f.name
                f.write(header)
            os.replace(temporary, hdr)
        finally:
            if temporary and os.path.exists(temporary):
                os.remove(temporary)

    print("%s: cso %d bytes -> %s" % (name, len(data), hdr))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=['FSRDFloorSeed', 'FSRDFloor', 'FSRDInputConv',
                                       'FSRDInputConvAdditive', 'FSRDOutputComp', 'all'])
    parser.add_argument('--dxc', help='DXC executable; otherwise FSRD_DXC, PATH, or latest installed SDK')
    options = parser.parse_args()
    compiler = dxc(options.dxc)
    print('DXC:', compiler, flush=True)
    subprocess.run([str(compiler), '--version'], check=True)
    # The verifier first: it fails in a second on a mirror that drifted, where the compiler
    # would say nothing and the shader would read the wrong parameter or resource.
    check = subprocess.run([sys.executable, VERIFY])
    if check.returncode != 0:
        raise SystemExit("mirror check failed; not compiling")
    if options.name == 'all':
        names = ['FSRDFloorSeed', 'FSRDFloor', 'FSRDInputConv',
                 'FSRDInputConvAdditive', 'FSRDOutputComp']
    elif options.name == 'FSRDInputConv':
        names = ['FSRDInputConv', 'FSRDInputConvAdditive']
    else:
        names = [options.name]
    for name in names:
        build(name, compiler)
