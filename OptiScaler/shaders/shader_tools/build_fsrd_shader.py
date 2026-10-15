"""Rebuild fsrd_preprocess shaders: cso + generated header (listing prefix + byte array).

Mirrors the layout the existing precompiled headers use, so the checked-in artifacts stay
in the same shape: an `#if 0` DXIL listing for reference, then the cso bytes.
FSRDInputConv builds both the original and enabled additive variants so an edit to
their shared source cannot leave either conversion PSO with a stale artifact; all dependent variants share the same source.
"""
import subprocess
import sys
import os
import argparse
import io
import tempfile
from concurrent.futures import ThreadPoolExecutor
from fsrd_toolchain import dxc

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PRE = "OptiScaler/shaders/fsrd_preprocess/precompile"
VERIFY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_fsrd_mirrors.py")


def publish_if_changed(path, data):
    if os.path.isfile(path):
        with open(path, 'rb') as stream:
            if stream.read() == data:
                return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=os.path.dirname(path), suffix='.tmp', delete=False) as stream:
            temporary = stream.name
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)


def compile_fused_sss(name, compiler, temporary):
    private = os.path.join(ROOT, PRE, 'sss_fused')
    pre = os.path.join(ROOT, PRE)
    original = 'FSRDInputConvSkinAdditive' if name.endswith('Additive') else 'FSRDInputConvSkin'
    common = [str(compiler), '-enable-16bit-types', '-O3', '-I', private, '-I', pre]
    def checked(args):
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
    bindings = os.path.join(temporary, 'bindings.rootsig')
    checked([str(compiler), '-T', 'rootsig_1_1', '-E', 'MainRS', '-I', private, '-I', pre,
             os.path.join(private, 'FSRDInputConvSkin.hlsl'), '-Fo', bindings])
    depth = os.path.join(temporary, 'depth.lib')
    core = os.path.join(temporary, 'core.lib')
    checked(common + ['-T', 'lib_6_3', '-exports', 'FusedSeedDepthBits', '-default-linkage', 'external',
                       os.path.join(private, 'FSRDSssDepthLibrary.hlsl'), '-Fo', depth])
    checked(common + ['-T', 'lib_6_3', '-exports', 'CSMain', '-default-linkage', 'internal',
                       os.path.join(private, original + '.hlsl'), '-Fo', core])
    unbound = os.path.join(temporary, 'unbound.cso')
    compiled = os.path.join(temporary, name + '.cso')
    asm = os.path.join(temporary, name + '.asm')
    checked([str(compiler), '-link', core + ';' + depth, '-T', 'cs_6_2', '-E', 'CSMain', '-Fo', unbound])
    checked([str(compiler), '-dumpbin', '-setrootsignature', bindings, unbound, '-Fo', compiled])
    checked([str(compiler), '-dumpbin', '-verifyrootsignature', bindings, compiled])
    result = subprocess.run([str(compiler), '-dumpbin', compiled], capture_output=True, text=True, check=True)
    with open(asm, 'w', encoding='utf-8') as stream:
        stream.write(result.stdout)
    return compiled, asm


def build(name, compiler):
    src = os.path.join(ROOT, PRE, name + ".hlsl")
    cso = os.path.join(ROOT, PRE, name + "_Shader.cso")
    hdr = os.path.join(ROOT, PRE, name + "_Shader.h")

    # A capture/probe may be reading the existing CSO. Compile elsewhere and
    # publish only a complete changed artifact, just as for the generated header.
    with tempfile.TemporaryDirectory(prefix=name+'_', dir=os.path.dirname(cso)) as temporary:
        compiled = os.path.join(temporary, name+'.cso')
        asm = os.path.join(temporary, name+'.asm')
        if name in ('FSRDInputConvSkinFused', 'FSRDInputConvSkinFusedAdditive'):
            compiled, asm = compile_fused_sss(name, compiler, temporary)
        else:
            args = [str(compiler), "-T", "cs_6_2", "-E", "CSMain", "-enable-16bit-types", "-O3",
                    "-Qstrip_debug", "-Qstrip_reflect", src, "-Fo", compiled, "-Fc", asm]
            res = subprocess.run(args, capture_output=True, text=True)
            if res.returncode != 0:
                print(res.stdout)
                print(res.stderr)
                raise SystemExit("dxc failed for " + name)
        with open(asm, "r", encoding="utf-8", errors="replace") as f:
            listing = "\n".join(
                line.rstrip() for line in f.read().replace("\r\n", "\n").splitlines()
            )
        with open(compiled, "rb") as f:
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
        newline = '\n'
        if os.path.isfile(hdr):
            with open(hdr, 'rb') as previous:
                if b'\r\n' in previous.read():
                    newline = '\r\n'
        header = f.getvalue().replace('\n', newline).encode('utf-8')

    # Avoid truncating a header while the IDE/indexer reads it. Reproducibility
    # checks should not rewrite identical artifacts at all; changed headers are
    # published atomically, so a failed write cannot leave an incomplete array.
    publish_if_changed(cso, data)
    publish_if_changed(hdr, header)

    print("%s: cso %d bytes -> %s" % (name, len(data), hdr))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=['FSRDNrdBridgeNativeDebug', 'FSRDNrdBridgeFlag', 'FSRDNrdBridgeFlagRoot', 'FSRDNrdBridgeCommit', 'FSRDNrdBridge', 'FSRDNrdBridgeCopy', 'FSRDNrdBridgeMotion', 'FSRDNrdBridgeMotionNative', 'FSRDNrdNativeTemporalCapture', 'FSRDNrdNativeTemporalCaptureRoot', 'FSRDGeometry', 'FSRDFlatDetailClassify', 'FSRDFlatDetailSeed', 'FSRDFlatDetailRefine', 'FSRDFlatTemporal', 'FSRDFlatTemporalLP', 'FSRDFlatTemporalStore', 'FSRDFlatDetailBase', 'FSRDFlatDetailApply', 'FSRDInputConv',
                                       'FSRDInputConvAdditive', 'RRTraceAdditive', 'FSRDOutputComp', 'FSRDCompareView',
                                                                                                                     'FSRDAlbedoTrustEvidence', 'FSRDAlbedoTrustPropagate',
                                       'FSRDSssPrepare', 'FSRDSssBlur', 'FSRDSkinPrefilter', 'FSRDInputConvSkin', 'FSRDInputConvSkinAdditive', 'FSRDInputConvSkinBounds', 'FSRDInputConvSkinBoundsAdditive', 'FSRDSkinBounds', 'FSRDSkinPrefilterTiled', 'FSRDInputConvSkinFused', 'FSRDInputConvSkinFusedAdditive', 'FSRDSssKernel', 'FSRDSssBlurTiled', 'FSRDProbeInputs', 'FSRDReference', 'FSRDLeak', 'FSRDAlbedoStabilise', 'FSRDFogStats', 'FSRDFogKappa', 'FSRDFogRank', 'FSRDFogSmooth', 'FSRDFogTarget', 'FSRDFogRoute', 'FSRDRecoveryLobeAccumulate', 'FSRDRecoveryLobeDown', 'FSRDRecoveryLobeBand', 'FSRDRRMotion', 'all'])
    parser.add_argument('--compile-only', action='store_true', help='Compile code without running mirror verification')
    parser.add_argument('--dxc', help='DXC executable; otherwise FSRD_DXC, PATH, or latest installed SDK')
    options = parser.parse_args()
    compiler = dxc(options.dxc)
    print('DXC:', compiler, flush=True)
    subprocess.run([str(compiler), '--version'], check=True)
    # The verifier first: it fails in a second on a mirror that drifted, where the compiler
    # would say nothing and the shader would read the wrong parameter or resource.
    if not options.compile_only:
        check = subprocess.run([sys.executable, VERIFY])
        if check.returncode != 0:
            raise SystemExit("mirror check failed; not compiling")
    if options.name == 'all':
        names = ['FSRDNrdBridgeNativeDebug', 'FSRDNrdBridgeFlag', 'FSRDNrdBridgeFlagRoot', 'FSRDNrdBridgeCommit', 'FSRDNrdBridge', 'FSRDNrdBridgeCopy', 'FSRDNrdBridgeMotion', 'FSRDNrdBridgeMotionNative', 'FSRDNrdNativeTemporalCapture', 'FSRDNrdNativeTemporalCaptureRoot', 'FSRDGeometry', 'FSRDFlatDetailClassify', 'FSRDFlatDetailSeed', 'FSRDFlatDetailRefine', 'FSRDFlatTemporal', 'FSRDFlatTemporalLP', 'FSRDFlatTemporalStore', 'FSRDFlatDetailBase', 'FSRDFlatDetailApply', 'FSRDInputConv',
                 'FSRDInputConvAdditive', 'RRTraceAdditive', 'FSRDOutputComp', 'FSRDCompareView',
                                                   'FSRDAlbedoTrustEvidence', 'FSRDAlbedoTrustPropagate',
                 'FSRDSssPrepare', 'FSRDSssBlur', 'FSRDSkinPrefilter', 'FSRDInputConvSkin', 'FSRDInputConvSkinAdditive', 'FSRDInputConvSkinBounds', 'FSRDInputConvSkinBoundsAdditive', 'FSRDSkinBounds', 'FSRDSkinPrefilterTiled', 'FSRDInputConvSkinFused', 'FSRDInputConvSkinFusedAdditive', 'FSRDSssKernel', 'FSRDSssBlurTiled', 'FSRDProbeInputs', 'FSRDReference', 'FSRDLeak', 'FSRDAlbedoStabilise', 'FSRDFogStats', 'FSRDFogKappa', 'FSRDFogRank', 'FSRDFogSmooth', 'FSRDFogTarget', 'FSRDFogRoute', 'FSRDRecoveryLobeAccumulate', 'FSRDRecoveryLobeDown', 'FSRDRecoveryLobeBand', 'FSRDRRMotion']
    elif options.name == 'FSRDInputConv':
        names = ['FSRDInputConv', 'FSRDInputConvAdditive', 'RRTraceAdditive', 'FSRDInputConvSkin', 'FSRDInputConvSkinAdditive', 'FSRDInputConvSkinBounds', 'FSRDInputConvSkinBoundsAdditive']
    else:
        names = [options.name]
    # Each shader compiles in its own dxc process and temporary directory and publishes
    # atomically, so independent shaders can build at the same time.
    with ThreadPoolExecutor(max_workers=min(len(names), 4, os.cpu_count() or 4)) as pool:
        list(pool.map(lambda name: build(name, compiler), names))
