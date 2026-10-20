"""Rebuild fsrd_preprocess shaders: cso + generated header (listing prefix + byte array).

Mirrors the layout the existing precompiled headers use, so the checked-in artifacts stay
in the same shape: an `#if 0` DXIL listing for reference, then the cso bytes.
FSRDNrdLobeRecovery rebuilds only its Reference, Down and Band graph stages.
FSRDInputConv builds both the original and enabled additive variants so an edit to
their shared source cannot leave either conversion PSO with a stale artifact; all dependent variants share the same source.

Two checked-in header formats exist, and this builder reproduces both exactly:
- Listing format (every generated header except the three below): `#if 0` DXIL
  listing for reference, then the cso byte array.
- Sealed provenance format (FSRDNrdLobeRecoveryReference/Down/Band only): those three
  ship the DXIL extracted from the validated full native signed no-correction graph
  (final-r1) rather than a standalone artifact, so their header opens with the
  provenance comment and the payload digest instead of a reference listing:
      // Exact DXIL from full native signed no-correction graph final-r1; no recompilation.
      // SHA-256: <digest of the cso bytes below>
  The standalone rebuild uses the same flags as the validated graph compiler and must
  reproduce the pinned digest in SEALED_PROVENANCE byte-for-byte. A digest mismatch is
  a build error: the builder never re-labels different bytes with the old graph
  provenance. If the change is intended, re-pin SEALED_PROVENANCE (and the provenance
  sentence, if the DXIL origin changed) in this file, then rebuild.
See tools/fsrd_frame_survey/NRD_SHADER_ARTIFACT_CONTRACT.md and
shader_tools/tests/test_fsrd_shader_artifact_contract.py for the tested contract.
"""
import subprocess
import sys
import os
import argparse
import hashlib
import io
import tempfile
from concurrent.futures import ThreadPoolExecutor
from fsrd_toolchain import dxc

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PRE = "OptiScaler/shaders/fsrd_preprocess/precompile"
VERIFY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_fsrd_mirrors.py")
NRD_LOBE_RECOVERY_SHADERS = (
    "FSRDNrdLobeRecoveryReference", "FSRDNrdLobeRecoveryDown", "FSRDNrdLobeRecoveryBand",
)
SEALED_PROVENANCE_COMMENT = (
    "// Exact DXIL from full native signed no-correction graph final-r1; no recompilation.\n"
)
# Pinned SHA-256 of the sealed Recovery payloads, exactly as shipped. The sealed
# header's `// SHA-256:` line and the checked-in *_Shader.cso both carry this digest.
SEALED_PROVENANCE = {
    "FSRDNrdLobeRecoveryReference": "5696c2ab2746f5107c3d3cfa2cd9b2f5fbafeab5a634fb9ffb2555b717a419cb",
    "FSRDNrdLobeRecoveryDown": "8a063414749af06c6abb00cba70ac53188a1c0b83fbaeeb360913e5a168712f8",
    "FSRDNrdLobeRecoveryBand": "b92089d1332e174c0202174cd8e850ec85f0a67a631e5b82bd047ada2df0c23b",
}


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


def compile_command(compiler, name, src, compiled, asm):
    """Exact dxc argv for a standalone rebuild, shared by build() and the contract test."""
    args = [str(compiler), "-T", "cs_6_2", "-E", "CSMain", "-enable-16bit-types", "-O3",
            "-Qstrip_debug", "-Qstrip_reflect", src, "-Fo", compiled, "-Fc", asm]
    if name in NRD_LOBE_RECOVERY_SHADERS:
        args += ["-I", os.path.dirname(src)]  # Match the validated graph compiler.
    return args


def listing_text(path):
    """dxc -Fc listing exactly as it is embedded in the generated header."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return "\n".join(
            line.rstrip() for line in f.read().replace("\r\n", "\n").splitlines()
        )


def array_bytes(name, data):
    """The `const unsigned char <name>_cso[] = {...};` block shared by both formats."""
    with io.StringIO() as f:
        f.write("const unsigned char %s_cso[] = {\n    " % name)
        for i, b in enumerate(data):
            f.write("0x%02x" % b)
            if i < len(data) - 1:
                f.write(",")
                f.write("\n    " if (i + 1) % 12 == 0 else " ")
        f.write("\n};\n")
        return f.getvalue()


def generated_header(name, data, listing, newline='\n'):
    """Complete generated-header bytes in the format the checked-in file uses.

    The three sealed Recovery headers take the provenance prefix (with the digest of
    `data`); every other shader takes the `#if 0` DXIL listing prefix. `newline`
    mirrors the checked-in file's line endings so regeneration is byte-exact.
    """
    with io.StringIO() as f:
        if name in SEALED_PROVENANCE:
            f.write(SEALED_PROVENANCE_COMMENT)
            f.write("// SHA-256: %s\n" % hashlib.sha256(data).hexdigest())
        else:
            f.write("#if 0\n")
            f.write(listing)
            f.write("\n\n#endif\n\n")
        f.write(array_bytes(name, data))
        return f.getvalue().replace('\n', newline).encode('utf-8')


def check_sealed_provenance(name, data):
    """Refuse to publish the sealed graph provenance over bytes that are not the graph's.

    A standalone rebuild of a sealed Recovery shader must reproduce the pinned
    digest exactly; anything else means the source no longer matches the DXIL that
    the provenance sentence vouches for, which is a conscious re-pin, never an
    automatic relabel.
    """
    digest = hashlib.sha256(data).hexdigest()
    pinned = SEALED_PROVENANCE.get(name)
    if pinned is not None and digest != pinned:
        raise SystemExit(
            "%s: rebuilt payload SHA-256 %s differs from the pinned native-graph digest %s."
            " The sealed provenance header must not be regenerated over different bytes."
            " If the change is intended, update SEALED_PROVENANCE in build_fsrd_shader.py"
            " (and the provenance sentence, if the DXIL origin changed), then rebuild."
            % (name, digest, pinned))
    return digest


def previous_newline(hdr):
    if os.path.isfile(hdr):
        with open(hdr, 'rb') as previous:
            if b'\r\n' in previous.read():
                return '\r\n'
    return '\n'


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
            res = subprocess.run(compile_command(compiler, name, src, compiled, asm),
                                 capture_output=True, text=True)
            if res.returncode != 0:
                print(res.stdout)
                print(res.stderr)
                raise SystemExit("dxc failed for " + name)
        listing = listing_text(asm)
        with open(compiled, "rb") as f:
            data = f.read()

    if name in SEALED_PROVENANCE:
        check_sealed_provenance(name, data)
    header = generated_header(name, data, listing, previous_newline(hdr))

    # Avoid truncating a header while the IDE/indexer reads it. Reproducibility
    # checks should not rewrite identical artifacts at all; changed headers are
    # published atomically, so a failed write cannot leave an incomplete array.
    publish_if_changed(cso, data)
    publish_if_changed(hdr, header)

    print("%s: cso %d bytes -> %s" % (name, len(data), hdr))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=['FSRDNrdBridgeNativeDebug', 'FSRDNrdBridgeFlag', 'FSRDNrdBridgeFlagRoot', 'FSRDNrdRawCapture', 'FSRDNrdRawCaptureRoot', 'FSRDNrdRawDecode', 'FSRDNrdRawPrePassCapture', 'FSRDNrdRawPrePassCaptureRoot', 'FSRDNrdRawPrePassDecode', 'FSRDNrdRawPrePassValidDecode', 'FSRDNrdBridgeGeometry', 'FSRDNrdBridgeGeometryMaterial', 'FSRDNrdBridgeGeometryMaterialParams', 'FSRDNrdBridgeFlagPixel', 'FSRDNrdBridgeFlagPixelRoot', 'FSRDNrdBridgeCommit', 'FSRDNrdBridgePureCommit', 'FSRDNrdBridgeSignalScale', 'FSRDRadianceScale', 'FSRDNrdLightingGuard', 'FSRDNrdLightingGuardApply', 'FSRDNrdBridgeTurnColour', 'FSRDNrdFlatPrepare', 'FSRDNrdFlatAccumulate', 'FSRDNrdFlatReferenceFilter', 'FSRDNrdFlatSelectPrep', 'FSRDNrdFlatSelectBlur', 'FSRDNrdFlatSelectApply', 'FSRDNrdFlatHistory', 'FSRDNrdFlatHybridPrep', 'FSRDNrdFlatHybridBlur', 'FSRDNrdFlatHybridApply', 'FSRDNrdFlatPolish', 'FSRDNrdBridge', 'FSRDNrdBridgeCopy', 'FSRDNrdBridgeMotion', 'FSRDNrdBridgeMotionNative', 'FSRDNrdBridgeMaterial', 'FSRDNrdBridgeMaterialParams', 'FSRDNrdNativeMaterialCapture', 'FSRDNrdNativeMaterialParamsCapture', 'FSRDNrdNativeTemporalCapture', 'FSRDNrdNativeTemporalCaptureRoot', 'FSRDGeometry', 'FSRDFlatDetailClassify', 'FSRDFlatDetailSeed', 'FSRDFlatDetailRefine', 'FSRDFlatTemporal', 'FSRDFlatTemporalLP', 'FSRDFlatTemporalStore', 'FSRDFlatDetailBase', 'FSRDFlatDetailApply', 'FSRDInputConv',
                                       'FSRDInputConvAdditive', 'RRTraceAdditive', 'FSRDOutputComp', 'FSRDCompareView', 'FSRDPostFlickPrepare', 'FSRDPostFlickApply',
                                       'FSRDColourTrackStats', 'FSRDColourTrackTrack', 'FSRDColourTrackApply',
                                       'FSRDPostMotionAnchorStatsRecall', 'FSRDPostMotionAnchorGain',
                                       'FSRDPostMotionAnchorApply',
                                                                                                                     'FSRDAlbedoTrustEvidence', 'FSRDAlbedoTrustPropagate',
                                       'FSRDSssPrepare', 'FSRDSssBlur', 'FSRDSkinPrefilter', 'FSRDInputConvSkin', 'FSRDInputConvSkinAdditive', 'FSRDInputConvSkinBounds', 'FSRDInputConvSkinBoundsAdditive', 'FSRDSkinBounds', 'FSRDSkinPrefilterTiled', 'FSRDInputConvSkinFused', 'FSRDInputConvSkinFusedAdditive', 'FSRDSssKernel', 'FSRDSssBlurTiled', 'FSRDProbeInputs', 'FSRDReference', 'FSRDLeak', 'FSRDAlbedoStabilise', 'FSRDFogStats', 'FSRDFogKappa', 'FSRDFogRank', 'FSRDFogSmooth', 'FSRDFogTarget', 'FSRDFogRoute', 'FSRDRecoveryLobeAccumulate', 'FSRDRecoveryLobeDown', 'FSRDRecoveryLobeBand', 'FSRDRRMotion', 'FSRDNrdLobeRecovery', *NRD_LOBE_RECOVERY_SHADERS, 'all'])
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
        names = ['FSRDNrdBridgeNativeDebug', 'FSRDNrdBridgeFlag', 'FSRDNrdBridgeFlagRoot', 'FSRDNrdRawCapture', 'FSRDNrdRawCaptureRoot', 'FSRDNrdRawDecode', 'FSRDNrdRawPrePassCapture', 'FSRDNrdRawPrePassCaptureRoot', 'FSRDNrdRawPrePassDecode', 'FSRDNrdRawPrePassValidDecode', 'FSRDNrdBridgeGeometry', 'FSRDNrdBridgeGeometryMaterial', 'FSRDNrdBridgeGeometryMaterialParams', 'FSRDNrdBridgeFlagPixel', 'FSRDNrdBridgeFlagPixelRoot', 'FSRDNrdBridgeCommit', 'FSRDNrdBridgePureCommit', 'FSRDNrdBridgeSignalScale', 'FSRDRadianceScale', 'FSRDNrdLightingGuard', 'FSRDNrdLightingGuardApply', 'FSRDNrdBridgeTurnColour', 'FSRDNrdFlatPrepare', 'FSRDNrdFlatAccumulate', 'FSRDNrdFlatReferenceFilter', 'FSRDNrdFlatSelectPrep', 'FSRDNrdFlatSelectBlur', 'FSRDNrdFlatSelectApply', 'FSRDNrdFlatHistory', 'FSRDNrdFlatHybridPrep', 'FSRDNrdFlatHybridBlur', 'FSRDNrdFlatHybridApply', 'FSRDNrdFlatPolish', 'FSRDNrdBridge', 'FSRDNrdBridgeCopy', 'FSRDNrdBridgeMotion', 'FSRDNrdBridgeMotionNative', 'FSRDNrdBridgeMaterial', 'FSRDNrdBridgeMaterialParams', 'FSRDNrdNativeMaterialCapture', 'FSRDNrdNativeMaterialParamsCapture', 'FSRDNrdNativeTemporalCapture', 'FSRDNrdNativeTemporalCaptureRoot', 'FSRDGeometry', 'FSRDFlatDetailClassify', 'FSRDFlatDetailSeed', 'FSRDFlatDetailRefine', 'FSRDFlatTemporal', 'FSRDFlatTemporalLP', 'FSRDFlatTemporalStore', 'FSRDFlatDetailBase', 'FSRDFlatDetailApply', 'FSRDInputConv',
                 'FSRDInputConvAdditive', 'RRTraceAdditive', 'FSRDOutputComp', 'FSRDCompareView', 'FSRDPostFlickPrepare', 'FSRDPostFlickApply',
                 'FSRDColourTrackStats', 'FSRDColourTrackTrack', 'FSRDColourTrackApply',
                                                   'FSRDAlbedoTrustEvidence', 'FSRDAlbedoTrustPropagate',
                 'FSRDSssPrepare', 'FSRDSssBlur', 'FSRDSkinPrefilter', 'FSRDInputConvSkin', 'FSRDInputConvSkinAdditive', 'FSRDInputConvSkinBounds', 'FSRDInputConvSkinBoundsAdditive', 'FSRDSkinBounds', 'FSRDSkinPrefilterTiled', 'FSRDInputConvSkinFused', 'FSRDInputConvSkinFusedAdditive', 'FSRDSssKernel', 'FSRDSssBlurTiled', 'FSRDProbeInputs', 'FSRDReference', 'FSRDLeak', 'FSRDAlbedoStabilise', 'FSRDFogStats', 'FSRDFogKappa', 'FSRDFogRank', 'FSRDFogSmooth', 'FSRDFogTarget', 'FSRDFogRoute', 'FSRDRecoveryLobeAccumulate', 'FSRDRecoveryLobeDown', 'FSRDRecoveryLobeBand', 'FSRDRRMotion']
        names.extend(NRD_LOBE_RECOVERY_SHADERS)
    elif options.name == 'FSRDNrdLobeRecovery':
        names = list(NRD_LOBE_RECOVERY_SHADERS)
    elif options.name == 'FSRDInputConv':
        names = ['FSRDInputConv', 'FSRDInputConvAdditive', 'RRTraceAdditive', 'FSRDInputConvSkin', 'FSRDInputConvSkinAdditive', 'FSRDInputConvSkinBounds', 'FSRDInputConvSkinBoundsAdditive']
    else:
        names = [options.name]
    # Each shader compiles in its own dxc process and temporary directory and publishes
    # atomically, so independent shaders can build at the same time.
    with ThreadPoolExecutor(max_workers=min(len(names), 4, os.cpu_count() or 4)) as pool:
        list(pool.map(lambda name: build(name, compiler), names))
