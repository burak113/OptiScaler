"""Production helper binding/lifetime parity, without editing old RR fixtures.

Default --prepare-only performs no DXC/compiler/native/GPU work. --run requires
the lead's serialized GPU/build grant and compares every output word against
the independently submitted, sealed13-pass graph. This is not a new quality or
signed-provider run: its RR arrays were produced by the cited prior signed run.
The separate --real-provider mode runs actual RRWrapper admission/failure cases
through the real signed export; static toy inputs prove integration, not quality.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import os
import re
import shlex
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(HERE), str(HERE.parent)]
from fsrd_toolchain import compile_cpp, dxc, visual_studio, _toolchain_environment
from test_fsrd_nrd_bridge_rr import bounded_run

REFERENCE = Path('F:/FSRD/sol_batch/15b-inputs/tests/nrd-recovery-native-final-r1/recovery-graph')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def declarations(sdk, interface):
    body = re.search(r'\b' + interface + r'\s*:\s*public\s+\w+\s*\{(.*?)\n\s*\};', sdk, re.S).group(1)
    body = re.sub(r'#if defined\(_MSC_VER\) \|\| !defined\(_WIN32\)\s*(.*?)#else.*?#endif', r'\1', body, flags=re.S)
    for match in re.finditer(r'virtual\s+(.*?)\s*=\s*0\s*;', body, re.S):
        signature = re.sub(r'/\*.*?\*/', '', match.group(1), flags=re.S).strip()
        marker = re.search(r'STDMETHODCALLTYPE\s+(\w+)\s*\(', signature)
        name = marker.group(1)
        parameters = signature[marker.end():signature.rfind(')')]
        parts, start, depth = [], 0, 0
        for index, char in enumerate(parameters):
            depth += char in '(['
            depth -= char in ')]'
            if char == ',' and depth == 0:
                parts.append(parameters[start:index]); start = index + 1
        parts.append(parameters[start:])
        names = []
        for part in parts:
            if part.strip() not in ('', 'void'):
                names.append(re.search(r'(\w+)\s*(?:\[[^]]*\])?\s*$', part).group(1))
        yield signature, name, names, signature[:signature.index('STDMETHODCALLTYPE')].strip() == 'void'


def forwarders(sdk):
    common = r'''
 std::atomic<ULONG> refs{1};
 ULONG STDMETHODCALLTYPE AddRef() override{return ++refs;}
 HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID g,UINT* s,void* d) override{return native->GetPrivateData(g,s,d);}
 HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID g,UINT s,const void* d) override{return native->SetPrivateData(g,s,d);}
 HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID g,const IUnknown* d) override{return native->SetPrivateDataInterface(g,d);}
 HRESULT STDMETHODCALLTYPE SetName(LPCWSTR n) override{return native->SetName(n);}
'''
    def methods(interface, special=None, observe=False):
        result = []
        for signature, name, args, void in declarations(sdk, interface):
            call = 'native->' + name + '(' + ','.join(args) + ')'
            body = ('' if void else 'return ') + call + ';'
            if special and name in special:
                body = special[name].replace('__CALL__', call)
            if observe:
                body = '++commands;' + ('++dispatches;' if name == 'Dispatch' else '') + body
            result.append(signature + ' override {' + body + '}')
        return '\n'.join(result)
    resource = r'''
struct LobeForwardResource final:ID3D12Resource{
 ComPtr<ID3D12Resource> native;std::shared_ptr<LobeRecovery::Family> family;ForwardStats* stats;
 LobeForwardResource(ID3D12Resource* r,std::shared_ptr<LobeRecovery::Family> f,ForwardStats* s):family(std::move(f)),stats(s){native.Attach(r);++stats->live;}
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID i,void** p) override{return native->QueryInterface(i,p);}
 ULONG STDMETHODCALLTYPE Release() override{auto n=--refs;if(!n){auto* raw=native.Detach();auto keep=family;auto* s=stats;delete this;
  const auto left=raw->Release();--s->live;++s->released;s->earlyCharge+=keep->graphBytes.load()==0;s->nonfinal+=left!=0;}return n;}
 HRESULT STDMETHODCALLTYPE GetDevice(REFIID i,void** p) override{return native->GetDevice(i,p);}
''' + common + methods('ID3D12Resource') + '\n};\n'
    special = {'CreateCommittedResource': r'''
 ++createCalls;if(createCalls==failCreateAt){*ppvResource=nullptr;return E_OUTOFMEMORY;}
 const auto result=__CALL__;
 if(SUCCEEDED(result)&&wrapResources&&riidResource==__uuidof(ID3D12Resource)){
  auto* raw=static_cast<ID3D12Resource*>(*ppvResource);
  try{*ppvResource=new LobeForwardResource(raw,family,stats);}catch(...){raw->Release();*ppvResource=nullptr;return E_OUTOFMEMORY;}}
 return result;
'''}
    device = r'''
struct LobeForwardDevice final:ID3D12Device{
 ComPtr<ID3D12Device> native;std::shared_ptr<LobeRecovery::Family> family;ForwardStats* stats;
 unsigned createCalls=0,failCreateAt=0;bool wrapResources=false;
 LobeForwardDevice(ID3D12Device* d,std::shared_ptr<LobeRecovery::Family> f,ForwardStats* s):native(d),family(std::move(f)),stats(s){}
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID i,void** p) override{if(i==__uuidof(ID3D12Device)){*p=static_cast<ID3D12Device*>(this);AddRef();return S_OK;}return native->QueryInterface(i,p);}
 ULONG STDMETHODCALLTYPE Release() override{auto n=--refs;if(!n)delete this;return n;}
''' + common + methods('ID3D12Device', special) + '\n};\n'
    observed = r'''
struct LobeObservedList final:ID3D12GraphicsCommandList{
 ComPtr<ID3D12GraphicsCommandList> native;unsigned commands=0,dispatches=0;
 explicit LobeObservedList(ID3D12GraphicsCommandList* list):native(list){}
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID i,void** p) override{return native->QueryInterface(i,p);}
 ULONG STDMETHODCALLTYPE Release() override{auto n=--refs;if(!n)delete this;return n;}
 HRESULT STDMETHODCALLTYPE GetDevice(REFIID i,void** p) override{return native->GetDevice(i,p);}
 D3D12_COMMAND_LIST_TYPE STDMETHODCALLTYPE GetType() override{return native->GetType();}
''' + common + methods('ID3D12GraphicsCommandList', observe=True) + '\n};\n'
    return resource + device + observed


def case(directory, storage):
    lines = (directory / 'chain.txt').read_text(encoding='utf-8').splitlines()
    assert lines[0] == 'FSRD_CHAIN_V1'
    _, _, resource_count, pass_count = map(int, lines[1].split())
    resources = [shlex.split(x) for x in lines[2:2 + resource_count]]
    for record in resources[:53]:
        expected = 3 if record[0].endswith('_geometry') else 2 if '_noise' in record[0] else 10 if storage == 'mixed' else 2
        assert int(record[5]) == expected, 'Independent graph storage map does not match the requested helper mode'
    passes = [shlex.split(x) for x in lines[2 + resource_count:]]
    assert len(passes) == pass_count and pass_count % 13 == 0
    frames, artifacts = [], []
    for first in range(0, pass_count, 13):
        reference, final = passes[first], passes[first + 12]
        assert reference[0].endswith('_reference') and final[0].endswith('_band0')
        assert list(map(int, reference[9:11])) == [11, 7]
        assert list(map(int, final[9:11])) == [18, 5]
        cb_path = Path(reference[2]); cb = cb_path.read_bytes()
        floats, control = struct.unpack('<28f', cb[:112]), struct.unpack('<4I', cb[112:])
        assert len(cb) == 128 and control[0] in (0, 1)
        assert tuple(floats[8:12]) == (1, 1, 4, .25)
        ids = list(map(int, reference[11:22]))[:7]
        names = ('spec', 'diff', 'rr_spec', 'rr_diff', 'depth', 'normals', 'motion')
        formats = (10, 10, 10, 10, 41, 24, 10)
        inputs = {}
        for name, expected_format, resource in zip(names, formats, ids):
            record = resources[resource]
            assert int(record[5]) == expected_format and record[7] != '-'
            path = Path(record[7]); assert path.is_file()
            inputs[name] = str(path)
            artifacts.append(dict(path=str(path), bytes=path.stat().st_size, sha256=sha(path)))
        output_ids = list(map(int, final[11 + 18:11 + 18 + 5]))[3:5]
        outputs = {}
        for signal, resource in zip(('spec', 'diff'), output_ids):
            record = resources[resource]; assert int(record[5]) == 10 and record[8] != '-'
            path = Path(record[8]); assert path.is_file()
            outputs[signal] = str(path)
            artifacts.append(dict(path=str(path), bytes=path.stat().st_size, sha256=sha(path)))
        frames.append(dict(frame_index=control[2], reset=not bool(control[0] & 1),
                           jitter_pixels=list(floats[12:14]), jitter_delta_uv=list(floats[14:16]), inputs=inputs, outputs=outputs))
        artifacts.append(dict(path=str(cb_path), bytes=128, sha256=sha(cb_path)))
    assert len(frames) == 64 and [x['frame_index'] for x in frames] == list(range(64))
    return dict(name=directory.name, width=int(floats[0]), height=int(floats[1]), frames=frames), artifacts


def prepare(out, reference, storage):
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(TEMP='F:/FSRD/tmp', TMP='F:/FSRD/tmp', OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
    sdk_env = _toolchain_environment(visual_studio())
    sdk_path = next(Path(p) / 'd3d12.h' for p in sdk_env['INCLUDE'].split(';') if (Path(p) / 'd3d12.h').is_file())
    generated = forwarders(sdk_path.read_text(encoding='utf-8'))
    (out / 'lobe_native_forwarders.h').write_text(generated, encoding='utf-8')
    (out / 'pch.h').write_text('#pragma once\n', encoding='utf-8')
    (out / 'State.h').write_text('#pragma once\n// Existing RR fixture supplies its explicit application adapter.\n', encoding='utf-8')
    shader_dir = out / 'precompile'; shader_dir.mkdir(exist_ok=True)
    shader_hashes = {}
    for role in ('Reference', 'Down', 'Band'):
        cso = reference / 'compiled' / (role + '.cso')
        code = cso.read_bytes(); shader_hashes[role] = sha(cso)
        # Fallback fixture include only; if production has an embedded header its
        # quoted include wins and must match the exact independent graph CSO.
        name = 'FSRDNrdLobeRecovery' + role
        (shader_dir / (name + '_Shader.h')).write_text('const unsigned char ' + name + '_cso[]={' + ','.join(map(str, code)) + '};\n', encoding='utf-8')
        production = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile' / (name + '_Shader.h')
        if production.exists():
            source = production.read_text(encoding='utf-8')
            numbers = re.findall(r'0x([0-9a-fA-F]{2})|\b(\d+)\b', source[source.index('{') + 1:source.rindex('}')])
            embedded = bytes(int(h, 16) if h else int(d) for h, d in numbers)
            assert embedded == code, 'Production shader bytes differ from parity reference: ' + role
    cases, artifacts = [], []
    for name in ('demod-r123', 'demod-r307'):
        value, files = case(reference / name, storage); cases.append(value); artifacts.extend(files)
    manifest = dict(schema='fsrd-nrd-lobe-recovery-helper-parity-v1', storage=storage, cases=cases)
    manifest_path = out / 'helper-parity.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    evidence = dict(compiler_executed=False, native_executed=False, gpu_executed=False,
                    sdk_header=str(sdk_path), sdk_sha256=sha(sdk_path), shader_sha256=shader_hashes,
                    reference=str(reference), storage=storage, immutable_reference_artifacts=artifacts,
                    helper_sha256=sha(ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdLobeRecovery_Dx12.h'),
                    fixture_sha256=sha(HERE / 'fsrd_nrd_lobe_recovery_fixture.cpp'))
    (out / 'source-preparation.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    return manifest_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--real-provider', action='store_true', help='run the separate actual signed RRWrapper/recovery integration mode')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--reference', type=Path, default=REFERENCE)
    parser.add_argument('--storage', choices=('fp32', 'mixed'), default='fp32')
    parser.add_argument('--output', type=Path, default=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15e-quality/lobe-recovery-helper')))
    args = parser.parse_args(); out = args.output
    if args.real_provider:
        assert args.storage == 'fp32', 'Production RRWrapper recovery uses the validated FP32 default'
    manifest = prepare(out, args.reference, args.storage)
    ast.parse(Path(__file__).read_text(encoding='utf-8'))
    if not args.run or args.prepare_only:
        print(json.dumps(dict(prepared=str(manifest), compiler_executed=False, native_executed=False, gpu_executed=False)))
        return
    os.environ['FSRD_CPP_CACHE'] = str(out / 'cache')
    shader = out / 'consumer.cso'
    subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-force-rootsig-ver', 'rootsig_1_0',
                    str(HERE / 'nrd_bridge_consumer_fixture.hlsl'), '-Fo', str(shader)], check=True)
    (out / 'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[]={' + ','.join(map(str, shader.read_bytes())) + '};\n', encoding='utf-8')
    exe = out / 'lobe_recovery_helper.exe'
    compile_cpp(HERE / 'fsrd_nrd_lobe_recovery_fixture.cpp', exe,
                ['d3d12.lib', 'dxgi.lib', 'd3dcompiler.lib', 'bcrypt.lib'],
                [out, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/nlohmann',
                 ROOT / 'external/streamline', ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
    command = [str(exe), str(manifest), str(out)] + (['--real-provider'] if args.real_provider else [])
    _, peak, elapsed, log = bounded_run(command, out / 'native_run')
    path = out / ('lobe-recovery-rr-result.json' if args.real_provider else 'lobe-recovery-helper-result.json')
    result = json.loads(path.read_text(encoding='utf-8'))
    assert result['debug_errors'] == result['debug_warnings'] == 0
    if args.real_provider:
        assert result['actual_signed_dispatches'] == 58
        assert result['successful_title_commits'] == 55
        assert result['private_graph_dispatches'] == 46 * 13
        assert result['physical_contexts'] == 14
        assert len(result['cases']) == 11
        assert result['inspection_checks'] > 0
        provider = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll')
        result['actual_provider'] = dict(path=str(provider), sha256=sha(provider))
        python_checks = 7
    else:
        assert len(result['cases']) == 2 and all(x['frames'] == 64 and x['dispatches'] == 832 for x in result['cases'])
        python_checks = 3
    result.update(python_checks=python_checks, elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log),
                  executable_sha256=sha(exe), source_preparation_sha256=sha(out / 'source-preparation.json'))
    path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
