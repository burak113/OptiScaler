"""Actual-host intervening raster work with native B output resource flags."""
from pathlib import Path
import json
import os
import test_fsrd_nrd_native_transactions as native
from test_fsrd_nrd_bridge_rr import bounded_run, DLL
from fsrd_toolchain import compile_cpp

RASTER = r'''
namespace NativeRaster {
using OmFn=void(WINAPI*)(ID3D12GraphicsCommandList*,UINT,D3D12_CPU_DESCRIPTOR_HANDLE*,BOOL,D3D12_CPU_DESCRIPTOR_HANDLE*);
OmFn original=nullptr;
void hkOMSetRenderTargets(ID3D12GraphicsCommandList* list,UINT count,D3D12_CPU_DESCRIPTOR_HANDLE* handles,BOOL contiguous,D3D12_CPU_DESCRIPTOR_HANDLE* depth){original(list,count,handles,contiguous,depth);}
__BODY__
void Attach(ID3D12GraphicsCommandList* list){auto** table=*reinterpret_cast<void***>(list);original=reinterpret_cast<OmFn>(table[46]);hr(DetourTransactionBegin());hr(DetourUpdateThread(GetCurrentThread()));need(DetourAttach(&(PVOID&)original,hkSurveyOMSetRenderTargets)==NO_ERROR,"actual OM observer attached");hr(DetourTransactionCommit());}
void Detach(){hr(DetourTransactionBegin());hr(DetourUpdateThread(GetCurrentThread()));need(DetourDetach(&(PVOID&)original,hkSurveyOMSetRenderTargets)==NO_ERROR,"actual OM observer detached");hr(DetourTransactionCommit());}
}
'''

def run():
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    exe, command, keywords = native.prepare(out)
    source = command[0]
    text = source.read_text()
    marker = 'int main(int argc,char** argv)try{'
    assert text.count(marker) == 1
    text = text.replace(marker, 'int PreservedNativeTransactionsMain(int argc,char** argv)try{')
    flags = 'if(i==7 || i==8) d.Flags|=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;'
    assert text.count(flags) == 1
    text = text.replace(flags, 'if(i==7 || i==8 || i==11 || i==12) d.Flags|=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;')
    res = (native.ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    om = native.baseline.res_function(res, 'hkSurveyOMSetRenderTargets')
    fixture = Path(__file__).with_name('fsrd_nrd_raster_outputs.cpp')
    source.write_text(text + '\n' + RASTER.replace('__BODY__', om) + fixture.read_text())
    prior = os.environ.get('CL')
    os.environ['CL'] = ((prior+' ') if prior else '')+'/bigobj'
    try:
        compile_cpp(*command, **keywords)
    finally:
        if prior is None: os.environ.pop('CL', None)
        else: os.environ['CL'] = prior
    cases = {}
    for mode in ('safe', 'reuse', 'contiguous', 'early', 'repeat', 'conflict', 'rebind', 'missing'):
        directory = out/mode
        directory.mkdir(parents=True, exist_ok=True)
        _, peak, elapsed, log = bounded_run([str(exe), str(directory), str(DLL), mode], directory/'native_run')
        value = json.loads((directory/'raster-outputs-result.json').read_text())
        assert value['debug_errors'] == value['debug_warnings'] == 0
        if mode in ('conflict', 'rebind', 'missing'):
            assert value['provider_dispatches'] == 1 and value['native_submissions'] == 1  # forwarded, never denied
        else:
            assert value['provider_dispatches'] == 4 and value['native_submissions'] == 2
        value.update(elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log))
        cases[mode] = value
    result = dict(cases=cases, native_checks=sum(v['native_checks'] for v in cases.values()), python_checks=16,
                  source_sha256=native.sha(source), fixture_sha256=native.sha(fixture), exe_sha256=native.sha(exe))
    (out/'raster-outputs-result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    run()
