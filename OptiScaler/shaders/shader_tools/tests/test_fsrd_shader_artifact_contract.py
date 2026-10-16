"""FSRD generated-shader artifact contract (F06, lane 15j-artifact-contract).

Pins, against the checked-in precompile artifacts and a fresh DXC compile:

- Format census: every precompile/*_Shader.h is in exactly one of the two formats the
  canonical builder emits -- the `#if 0` DXIL listing format, or the sealed provenance
  format used only by FSRDNrdLobeRecoveryReference/Down/Band (DXIL extracted from the
  validated full native signed no-correction graph final-r1).
- Byte equality: for the 13 shaders whose sources changed in the audited window (the
  F06 set, Recovery trio included), a fresh standalone DXC rebuild reproduces the
  checked-in header and cso bytes exactly -- full-file equality, not just the embedded
  array. The sealed trio's header is rebuilt in its sealed format with its payload
  digest; everything else in the listing format.
- Pin enforcement: SEALED_PROVENANCE digests match the shipped payloads, and the
  builder's provenance guard refuses to re-label drifted bytes with the old graph
  provenance (negative control, pure CPU).

CPU-only: the only execution is DXC compilation (no D3D12 device, no game, no GPU
lock needed). Default set is the F06 affected-13; pass --shaders <name> (repeatable)
to compile additional shaders through the same proof. The two fused SSS shaders use
the separate rootsignature-link pipeline and are covered by their own tests, not here.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import dxc
import build_fsrd_shader as builder

PRE = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile'
SEALED = set(builder.SEALED_PROVENANCE)
# The audited F06 set: every shader affected by the changed sources, Recovery trio
# included. 10 listing-format + 3 sealed, rebuilt by the independent Sol audit with
# 13/13 CSO and embedded-array equality; this test re-proves it on every run.
AFFECTED = (
    'FSRDNrdBridge', 'FSRDNrdBridgeGeometry', 'FSRDNrdBridgeGeometryMaterial',
    'FSRDNrdBridgeGeometryMaterialParams', 'FSRDNrdBridgeMaterial',
    'FSRDNrdBridgeMaterialParams', 'FSRDNrdBridgeMotion', 'FSRDNrdBridgeMotionNative',
    'FSRDNrdRawPrePassDecode', 'FSRDNrdRawPrePassValidDecode',
    *builder.NRD_LOBE_RECOVERY_SHADERS,
)
CHECKS = 0


def need(value, name):
    global CHECKS
    CHECKS += 1
    if not value:
        raise AssertionError(name)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def embedded_payload(text):
    """The cso bytes encoded by a generated header's array, whatever the prefix format."""
    body = text[text.index('= {') + 3:text.rindex('}')]
    return bytes(int(h, 16) for h in re.findall(r'0x([0-9a-fA-F]{2})', body))


def parse_header(name):
    """Classify one checked-in header and return (format, payload, full bytes)."""
    path = PRE / (name + '_Shader.h')
    raw = path.read_bytes()
    need(b'\r\n' not in raw, name + ': generated header is LF (eol=lf is pinned)')
    text = raw.decode('utf-8')
    payload = embedded_payload(text)
    if name in SEALED:
        prefix = (
            builder.SEALED_PROVENANCE_COMMENT
            + '// SHA-256: %s\n' % hashlib.sha256(payload).hexdigest()
        ).encode('utf-8')
        need(raw.startswith(prefix), name + ': sealed prefix is the provenance comment plus the payload digest')
        need(b'#if 0' not in raw, name + ': sealed header embeds no DXIL listing')
        need(name in builder.NRD_LOBE_RECOVERY_SHADERS, name + ': sealed format is reserved for the Recovery trio')
        return 'sealed', payload, raw
    need(raw.startswith(b'#if 0\n'), name + ': listing header opens with #if 0')
    marker = b'\n#endif\n\nconst unsigned char ' + name.encode() + b'_cso[] = {\n'
    need(marker in raw, name + ': listing closes with #endif right before the array')
    need(raw.endswith(b'\n};\n'), name + ': array ends with the canonical terminator')
    need(b'// Exact DXIL from' not in raw, name + ': listing header carries no sealed provenance comment')
    return 'listing', payload, raw


def format_census():
    """Every generated header is exactly one of the two formats; the array writer round-trips."""
    names = sorted(path.name[:-len('_Shader.h')] for path in PRE.glob('*_Shader.h'))
    need(len(names) == 81, 'the census covers every checked-in generated header')
    seen = {}
    for name in names:
        kind, payload, raw = parse_header(name)
        seen[name] = kind
        # Re-serialize the array region with the canonical writer: identical bytes.
        array = builder.array_bytes(name, payload).encode('utf-8')
        need(raw.endswith(array), name + ': array region is exactly the canonical writer output')
        cso = PRE / (name + '_Shader.cso')
        need(cso.is_file(), name + ': generated header has its cso twin')
        need(cso.read_bytes() == payload, name + ': embedded array equals the checked-in cso bytes')
        if kind == 'sealed':
            need(sha(cso) == builder.SEALED_PROVENANCE[name],
                 name + ': pinned SEALED_PROVENANCE digest equals the shipped cso digest')
    sealed_census = sorted(name for name, kind in seen.items() if kind == 'sealed')
    need(sealed_census == sorted(SEALED), 'the sealed format is used by exactly the pinned trio: ' + ', '.join(sealed_census))
    return seen


def pin_guard_controls():
    """The provenance guard refuses drifted payloads; drifted bytes cannot fake the header."""
    for name in sorted(SEALED):
        shipped = (PRE / (name + '_Shader.cso')).read_bytes()
        need(builder.check_sealed_provenance(name, shipped) == sha(PRE / (name + '_Shader.cso')),
             name + ': the guard accepts the shipped payload')
        drifted = shipped[:-1] + bytes([shipped[-1] ^ 0xFF])
        try:
            builder.check_sealed_provenance(name, drifted)
        except SystemExit as exit_:
            need('SEALED_PROVENANCE' in str(exit_), name + ': guard failure names the re-pin escape hatch')
        else:
            raise AssertionError(name + ': guard must refuse a drifted payload')
        _, payload, raw = parse_header(name)
        need(builder.generated_header(name, drifted, '') != raw,
             name + ': drifted bytes cannot regenerate the sealed header')
        need(builder.generated_header(name, payload, '') == raw,
             name + ': shipped bytes regenerate the sealed header byte-for-byte without a listing')


def fresh_compile(names):
    """A fresh standalone DXC rebuild reproduces the checked-in artifacts exactly."""
    compiler = dxc()
    evidence = {}
    with tempfile.TemporaryDirectory(prefix='fsrd_artifact_contract_') as temporary:
        for name in names:
            src = os.path.join(builder.ROOT, builder.PRE, name + '.hlsl')
            compiled = os.path.join(temporary, name + '.cso')
            asm = os.path.join(temporary, name + '.asm')
            result = subprocess.run(builder.compile_command(compiler, name, src, compiled, asm),
                                    capture_output=True, text=True)
            need(result.returncode == 0, name + ': fresh dxc compile succeeds: ' + result.stderr[-400:])
            data = Path(compiled).read_bytes()
            expected = builder.generated_header(name, data, builder.listing_text(asm))
            kind, _, raw = parse_header(name)
            need(expected == raw, name + ': fresh rebuild reproduces the checked-in %s header byte-for-byte' % kind)
            need(data == (PRE / (name + '_Shader.cso')).read_bytes(),
                 name + ': fresh rebuild reproduces the checked-in cso bytes')
            evidence[name] = dict(format=kind, cso_sha256=hashlib.sha256(data).hexdigest(),
                                  cso_bytes=len(data), header_sha256=hashlib.sha256(raw).hexdigest(),
                                  header_bytes=len(raw))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shaders', action='append', default=[],
                        help='additional shader to prove through the fresh-compile path')
    parser.add_argument('--skip-compile', action='store_true',
                        help='format census and pin controls only (no dxc execution)')
    args = parser.parse_args()
    seen = format_census()
    pin_guard_controls()
    names = list(AFFECTED)
    for extra in args.shaders:
        need(extra in seen, 'unknown shader: ' + extra)
        if extra not in names:
            names.append(extra)
    evidence = dict(schema='fsrd-shader-artifact-contract-v1',
                    headers=len(seen), sealed=sorted(SEALED),
                    compiled=sorted(names), compile_skipped=bool(args.skip_compile))
    if not args.skip_compile:
        evidence['fresh_compiles'] = fresh_compile(names)
    print(json.dumps(evidence, indent=1))
    print('fsrd shader artifact contract verified: %d checks, %d formats censused, %d fresh compiles'
          % (CHECKS, len(seen), 0 if args.skip_compile else len(names)))


if __name__ == '__main__':
    main()
