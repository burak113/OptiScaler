"""Independent source/log/float-bit audit of query-only utility; no execution."""
import ast,hashlib,json,re,struct
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
CASE=ROOT/'tools_tmp/provider_defaults_query_20260930';STUDY=CASE/'evidence'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
rp=STUDY/'results.json';before=sha(rp);r=json.loads(rp.read_text());d=r['source_derivation']
assert r['contexts']==1 and r['native_dispatches']==0 and r['returncode']==0 and r['queries_before_effect_configuration']
assert not r['query_utility_is_existing_pinned_runner']
assert sha(Path(d['parent']))==d['parent_sha256'] and sha(CASE/'analyze.py')==d['script_sha256']
assert sha(STUDY/'query_defaults.cpp')==d['generated_source_sha256']
assert sha(STUDY/'query_defaults.exe')==r['runner_sha256'] and sha(Path(r['provider_path']))==r['provider_sha256']
assert sha(STUDY/'runner.log')==r['log_sha256'] and sha(STUDY/'job.txt')==r['job_sha256']
for identity in r['input_identities'].values():assert sha(Path(identity['path']))==identity['sha256']
tree=ast.parse((CASE/'analyze.py').read_text())
block_node=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='block' for t in n.targets))
block=ast.literal_eval(block_node.value)
text=Path(d['parent']).read_text()
for include in ('api/include/ffx_api_loader.h','api/include/dx12/ffx_api_dx12.h','denoisers/include/ffx_denoiser.h'):
    old='../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/'+include;assert text.count(old)==1
    text=text.replace(old,(ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX'/include).as_posix(),1)
anchor='    ff(api.CreateContext(&context,&create.header,nullptr),"create RR");';assert text.count(anchor)==1
text=text.replace(anchor,anchor+'\n'+block,1)
assert text==(STUDY/'query_defaults.cpp').read_text()
assert 'float value=std::nanf("")' in block
assert 'FFX_API_QUERY_DESC_TYPE_DENOISER_GET_DEFAULT_KEYVALUE,nullptr},defaultKeys[i],1,&value' in block
assert 'return queryValidationErrors||sdkErrors?2:0;' in block
assert text.index('return queryValidationErrors||sdkErrors?2:0;')<text.index('if(tuning)')<text.index('api.Dispatch(')
log=(STUDY/'runner.log').read_text()
assert 'debug_layer=1' in log and 'query_only=1 context_create_flags=2 signals=34 requested_api=4202496 dispatches=0' in log
assert all(re.search(r'\b'+k+r'=0\b',log) for k in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'))
header=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h';htext=header.read_text()
assert 'FFX_API_QUERY_DESC_TYPE_DENOISER_GET_DEFAULT_KEYVALUE FFX_API_MAKE_EFFECT_SUB_ID(FFX_API_EFFECT_ID_DENOISER, 0x81)' in htext
names={6:'DISOCCLUSION_THRESHOLD',1:'CROSS_BILATERAL_NORMAL_STRENGTH',2:'STABILITY_BIAS',3:'MAX_RADIANCE',4:'RADIANCE_CLIP_STD_K',5:'GAUSSIAN_KERNEL_RELAXATION'}
for key,name in names.items():assert re.search(r'FFX_API_CONFIGURE_DENOISER_KEY_'+name+r'\s*=\s*'+str(key)+r'\b',htext)
parsed=re.findall(r'default_key=(\d+) query_result=(\d+) finite=(\d+) float_bits=(\d+) value=(\S+)',log)
assert len(parsed)==6 and [int(x[0]) for x in parsed]==[6,1,2,3,4,5]
keys=[]
for stored,parts in zip(r['keys'],parsed):
    key,code,finite,bits,decimal=parts;key,code,finite,bits=map(int,(key,code,finite,bits))
    assert stored['key_id']==key and stored['returncode']==code==0 and stored['finite'] and finite==1 and stored['measured']
    assert stored['float32_bits']==bits
    exact=struct.unpack('<f',struct.pack('<I',bits))[0]
    assert np.isfinite(exact) and struct.unpack('<I',struct.pack('<f',float(decimal)))[0]==bits
    assert struct.unpack('<I',struct.pack('<f',stored['value']))[0]==bits
    keys.append(dict(key_id=key,name=names[key],float32_bits=bits,exact_decoded_float32=exact,reported_decimal=stored['value'],query_returncode=0))
assert all((STUDY/f'unused_{k}.bin').stat().st_size==0 for k in ('diffuse','specular'))
assert sha(rp)==before
result=dict(schema='default-query-independent-audit-v1',analysis_sha256=sha(__file__),report_sha256=before,
    source_derivation_reproduced_exactly=True,header_key_ID_and_query_descriptor_contract_valid=True,
    utility_binary_sha256=r['runner_sha256'],provider_sha256=r['provider_sha256'],job_sha256=r['job_sha256'],
    utility_contexts=1,native_dispatches=0,query_before_effect_key_Configure=True,all_six_return_OK_finite_floatbits_valid=True,
    keys=keys,all_input_files_rehashed=True,log_sha256=r['log_sha256'],header_sha256=sha(header),
    all_original_evidence_unchanged=True,quality_accepted=False,
    limitations=['GET_DEFAULT exposes provider defaults, not current configured or automatically optimized live settings.',
        'Separate compiled utility; original pinned runner does not query keys. Global-debug Configure runs beforecontextcreation, but no effect-key Configure or dispatch runs.',
        'Measured defaults scoped to this DLL,driver/adapter,API1.2,signal34,validationflag2,max128x80 fresh context; not proved universal across providers/contexts.',
        'Utility creates resources/opens input files but performs no upload/native dispatch; defaults are not image-quality measurements.',
        'No caller bug, tuning parameter causation or quality/game acceptance inferred.'])
out=HERE/'query_audit.json';assert not out.exists();out.write_text(json.dumps(result,indent=2)+'\n');print('audit_sha256',sha(out))
