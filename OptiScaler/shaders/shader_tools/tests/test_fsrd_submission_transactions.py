"""Actual submission-body extraction: conservative selector, full transaction, two threads.

The recorder/FG/bootstrap and native retirement effects are explicit adapters.
No physical Release coverage, signed AMD output, or full coordinator proof is claimed.
"""
from pathlib import Path
import hashlib
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp, visual_studio, _toolchain_environment
from test_recorded_compute_submission import fake_com
from test_fsrd_nrd_bridge_rr import bounded_run

ROOT = Path(__file__).resolve().parents[4]


def definition(source, signature):
    search = 0
    while True:
        start = source.index(signature, search)
        opening = source.index('(', start)
        depth, end = 1, opening + 1
        while depth:
            depth += (source[end] == '(') - (source[end] == ')')
            end += 1
        brace = source.index('{', end)
        declaration = source.find(';', end, brace)
        if declaration != -1:
            search = declaration + 1
            continue
        break
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def run():
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/13e-e2e/tests/submission_transactions'))
    output.mkdir(parents=True, exist_ok=True)
    environment = _toolchain_environment(visual_studio())
    sdk = next((Path(path) / 'd3d12.h' for path in environment['INCLUDE'].split(';')
                if (Path(path) / 'd3d12.h').is_file())).read_text()
    source = (ROOT / 'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    signatures = (
        'static bool RequiredComputeSubmissionAllowed(',
        'std::shared_ptr<RecordedComputeLease::Submission> ResTrack_Dx12::BeforeComputeSubmission(',
        'void ResTrack_Dx12::hkExecuteCommandLists(',
        'static bool HasRetainedSubmissionParticipant(',
        'void ResTrack_Dx12::hkSurveyExecuteCommandLists(',
    )
    bodies = {signature: definition(source, signature) for signature in signatures}
    fixture = Path(__file__).with_name('fsrd_submission_transaction_fixture.cpp').read_text()
    fixture = fixture.replace('#include "__ROOT__/OptiScaler/misc/RecordedComputeLease_Dx12.h"',
        '#include "__ROOT__/OptiScaler/misc/RecordedComputeLease_Dx12.h"\n#include "__ROOT__/OptiScaler/misc/NrdBridgeDescriptorAdmission_Dx12.h"', 1)
    declaration = 'static bool HasRetainedSubmissionParticipant(UINT,ID3D12CommandList* const*) noexcept;\n'
    generated = fixture.replace('__ROOT__', ROOT.as_posix()).replace('__PRODUCTION__', declaration+'\n'.join(bodies.values()))
    generated = generated.replace('__FAKE_COM__', fake_com(sdk))
    path = output / 'submission_transactions.cpp'
    path.write_text(generated)
    exe = output / 'submission_transactions.exe'
    os.environ['FSRD_CPP_CACHE'] = str(output / 'cache')
    compile_cpp(path, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'bcrypt.lib'), (ROOT / 'external/nlohmann',))
    results = {}
    for mode in (('cpu',) if '--cpu-only' in sys.argv else ('gpu',) if '--gpu-only' in sys.argv else ('cpu', 'gpu')):
        text, peak, elapsed, native_log = bounded_run([str(exe), mode], output / mode)
        value = json.loads(text)
        value.update(peak_resident_bytes=peak, elapsed_seconds=elapsed, native_log=str(native_log))
        results[mode] = value
    values = {
        'results': results,
        'actual_body_sha256': {signature: hashlib.sha256(body.encode()).hexdigest() for signature, body in bodies.items()},
        'scope': 'actual production selector/survey-hook/Execute-hook/Before resolver and lease/Birth/native-GUID/perf headers; recorder/FG/retirement-effects adapters; fake COM CPU plus real WARP threaded queues; no physical Release/AMD/coordinator completeness claim',
    }
    (output / 'result.json').write_text(json.dumps(values, indent=2) + '\n')
    print(json.dumps(values, indent=2))


if __name__ == '__main__':
    run()
