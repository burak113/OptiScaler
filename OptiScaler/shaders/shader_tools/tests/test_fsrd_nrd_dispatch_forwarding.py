"""CPU proof of the actual dispatch/opaque/state detours; no GPU or real RR.

The coordinator, recorder and D3D cache are explicit call-order spies. Production
hook bodies, SDK ABI, lifetime gate and method-specific forwarding scope are real.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = Path(os.environ.get('FSRD_NRD_PRODUCTION_ROOT', Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
from test_fsrd_nrd_root_restore import function



def member_function(source, name):
    at = source.index('ResTrack_Dx12::'+name+'(')
    start = source.rfind('\n', 0, at)+1
    return function(source, source[start:at]+'ResTrack_Dx12::'+name+'(').replace('ResTrack_Dx12::', '')


def prepare(out):
    res = (ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    survey = (ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').read_text()
    api = (ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.h').read_text()
    enums = []
    for name in ('DispatchKind', 'DispatchDisposition'):
        found = re.search(r'enum class '+name+r'\s*:[^{]+\{[^}]+\};', api)
        assert found, f'Actual public {name} API is required'
        enums.append(found.group())
    bodies = '\n'.join(member_function(res, name) for name in ('hkSurveyDispatch', 'hkSurveyExecuteBundle'))
    bodies += '\n'+function(res, 'static void STDMETHODCALLTYPE hkBridgeClearState(')
    bodies += '\n'+function(res, 'static void STDMETHODCALLTYPE hkBridgeSetPredication(')
    indirect = function(survey, 'void STDMETHODCALLTYPE Indirect(')
    internal = next(x for x in survey.splitlines() if x.startswith('struct InternalScope '))
    hook = member_function(res, 'HookCommandList')
    detach = member_function(res, 'ReleaseDeviceHooks')
    # Exact installed SDK vtable, not an independently copied method-number table.
    sdk = Path(os.environ.get('FSRD_D3D12_SDK_HEADER',
        r'C:/Program Files (x86)/Windows Kits/10/Include/10.0.26100.0/um/d3d12.h'))
    text = sdk.read_text(errors='replace')
    start = text.index('typedef struct ID3D12GraphicsCommandListVtbl')
    end = text.index('} ID3D12GraphicsCommandListVtbl', start)
    slots = re.findall(r'\( STDMETHODCALLTYPE \*(\w+) \)', text[start:end])
    assert slots.index('ClearState') == 11 and slots.index('SetPredication') == 55
    assert 'o_ClearState = (PFN_ClearState) pVTable[11]' in hook
    assert 'o_SetPredication = (PFN_SetPredication) pVTable[55]' in hook
    for name in ('ClearState', 'SetPredication'):
        assert f'DetourAttach(&(PVOID&) o_{name},hkBridge{name})' in hook
        assert f'DetourDetach(&(PVOID&) o_{name},hkBridge{name})' in detach
    assert 'clearStateAttachResult != NO_ERROR' in hook and 'predicationAttachResult' in hook
    source = Path(__file__).with_name('fsrd_nrd_dispatch_forwarding_fixture.cpp').read_text()
    for key, value in {'ROOT': ROOT.as_posix(), 'ENUMS': '\n'.join(enums), 'HOOKS': bodies,
                       'INDIRECT': indirect, 'INTERNAL': internal}.items():
        source = source.replace('__'+key+'__', value)
    assert '__HOOKS__' not in source
    out.mkdir(parents=True, exist_ok=True)
    target = out/'dispatch_forwarding.cpp'
    target.write_text(source)
    metadata = {'production_root': str(ROOT), 'sources': {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp',
                  ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp',
                  ROOT/'OptiScaler/misc/NrdBridgeTitleCallbacks_Dx12.h')},
        'sdk': str(sdk), 'clear_state_slot': slots.index('ClearState'),
        'predication_slot': slots.index('SetPredication'), 'source_checks': 10,
        'scope': 'Actual extracted hook bodies; explicit CPU coordinator/recorder/cache spies; no GPU/RR quality claim'}
    (out/'source.json').write_text(json.dumps(metadata, indent=2)+'\n')
    return target, metadata


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15a-motion/dispatch-forwarding'))
    source, metadata = prepare(out)
    if args.prepare_only:
        print(json.dumps(metadata))
        return
    exe = out/'dispatch_forwarding.exe'
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'bcrypt.lib'),
                (ROOT/'external/nlohmann', ROOT/'OptiScaler'))
    process = subprocess.run([str(exe)], capture_output=True, text=True,
                             creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (out/'native.stdout.log').write_text(process.stdout)
    (out/'native.stderr.log').write_text(process.stderr)
    process.check_returncode()
    result = json.loads(process.stdout)
    result.update(metadata)
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    run()
