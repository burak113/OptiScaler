"""CPU regression scenarios for per-frame RR failure recovery."""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp


def host_methods(source):
    signatures = (
        "bool FSRDFeatureDx12::WantsFsrRR(",
        "RRResult FSRDFeatureDx12::ClassifyRayRegenerationFailure(",
        "void FSRDFeatureDx12::FailRayRegeneration(",
        "void FSRDFeatureDx12::RequestGameNative(",
        "void FSRDFeatureDx12::OnEvaluationStarting(",
        "bool FSRDFeatureDx12::EvaluateNative(",
        "bool FSRDFeatureDx12::EvaluateInternal(",
        "bool FSRDFeatureDx12::EvaluateFallback(",
        "void FSRDFeatureDx12::OnEvaluationFinished(",
        "RRResult FSRDFeatureDx12::ResolveSignalTypes(",
    )
    methods = []
    for signature in signatures:
        start = source.index(signature)
        methods.append(source[start:source.index("\n}\n", start) + 3])
    return "\n\n".join(methods)


def run():
    root = Path(__file__).resolve().parents[4]
    out = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", root / "tools_tmp/fsrd_rr_recovery_20261005/tests"))
    exe = out / "rr_retry_policy/fsrd_rr_retry_policy_test.exe"
    compile_cpp(Path(__file__).with_name("fsrd_rr_retry_policy_test.cpp"), exe,
                include_dirs=(root / "external/FidelityFX-SDK/ffx-api/include/ffx_api",))
    subprocess.run([str(exe)], check=True)

    # Compile the real host recovery methods with controlled provider/device
    # outcomes. This checks their integration, including native fallback and
    # the NGX capability fields that can otherwise prevent automatic recovery.
    generated = exe.parent
    source = (root / "OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp").read_text(encoding="utf-8-sig")
    (generated / "fsrd_rr_host_methods.inc").write_text(host_methods(source), encoding="utf-8")
    runtime = (root / "OptiScaler/gpu_time/FSRDStageTimings_Dx12.h").read_text(encoding="utf-8-sig")
    (generated / "fsrd_rr_host_runtime.inc").write_text(runtime[runtime.index("struct FSRDRuntimeSnapshot"):],
                                                       encoding="utf-8")
    host_exe = generated / "fsrd_rr_host_recovery_test.exe"
    compile_cpp(Path(__file__).with_name("fsrd_rr_host_recovery_test.cpp"), host_exe,
                include_dirs=(generated, root / "external/FidelityFX-SDK/ffx-api/include/ffx_api"))
    subprocess.run([str(host_exe)], check=True)


if __name__ == "__main__":
    run()
