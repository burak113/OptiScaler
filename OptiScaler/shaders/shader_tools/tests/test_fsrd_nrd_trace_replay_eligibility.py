"""CPU-only contract replay over an actual two-frame recorder fixture prefix.

The source must be the recorder fixture, not an invented provider witness.
Only published payloads are copied into bounded adversarial test storage.
No compiler, LoadLibrary, provider or GPU process is started.
"""
from pathlib import Path
import argparse
import json
import os

from fsrd_nrd_trace_replay import inspect_capture
from test_fsrd_nrd_trace_replay_contract import exercise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    output = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", "F:/FSRD/sol_batch/15d-guides/replay-eligibility-cpu"))
    output.mkdir(parents=True, exist_ok=True)
    replay = inspect_capture(args.capture)
    assert replay["published_frames"] == 2
    assert replay["full_temporal_replay_eligible"] is False
    assert replay["ineligibility_reasons"] == ["actual_provider_binary_attestation_unavailable"]
    for frame in replay["frames"]:
        assert len(frame["inputs"]) == 7
        for row in frame["inputs"].values():
            assert row["source_native_resource_desc"]["flags"] in (0, 4)
            assert row["source_state"] == 64
    result = exercise(args.capture, output / "adversarial-published-prefix")
    assert result["checks"] == 48
    result.update(compiler_executed=False, provider_loaded=False, actual_sdk_dispatches=0,
                  source_capture=str(args.capture.resolve()),
                  scope="CPU validation of real fenced recorder fixture bytes plus strict negative mutations; no actual provider attestation")
    (output / "eligibility-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
