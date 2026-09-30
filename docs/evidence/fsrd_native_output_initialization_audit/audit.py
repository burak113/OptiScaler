"""CPU-only independent forensic audit; never imports/runs the producer driver."""
from pathlib import Path
from datetime import datetime, timezone
import ast, difflib, hashlib, itertools, json, re, shlex, struct, subprocess
import numpy as np

ROOT = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
HERE = Path(__file__).resolve().parent
WORK = ROOT/'tools_tmp/native_output_initialization_diagnostic_20260930'
ARCHIVE = ROOT/'docs/evidence/fsrd_native_output_initialization'
BASE = ROOT/'tools_tmp/native_continuous_harmonic_remaining_20260930/evidence/wave/harmonic_pilot'
ORIGINAL = ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_rr_runner.cpp'
DLL = ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
HEAD = '18550af88f665103e11c8e08d7c701118be1d156'
SHAS = {'original':'f6cfbecc4704d7f4f891f5c2ae88baf69546a316a9738ed03da0413d6ef0d077',
        'source':'2d07165f7da6bc1b1cc65eff0982b78ca35f1a062c3331b642fa75d9b8b7a187',
        'exe':'9c9e15c2c0eb1f4f8a59cf67d105eef3db05377b8c296869e6e253b9a0786496',
        'dll':'48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3',
        'manifest':'3fb82107d48c5e13b02f01c438c6f680f4153ac81ed6bdca0dbab210678a10d4',
        'summary':'cb9e85c220e9ce09f2597f481a0b6980bf1fdd77dace67f6098fcf885c5212af'}
TAGS = [f'round0_mode{i}' for i in range(6)] + [f'round1_mode{i}' for i in range(5,-1,-1)]
LOBES = ('diffuse.bin','specular.bin')
FORMATS = [41,10,24,28,28,10,10]
UPLOADS = [1,1,1,1,1,64,64]
PIXELS = 64*80*128

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def readj(p): return json.loads(Path(p).read_text())
def identity(p):
    p = Path(p)
    return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(name, value):
    with (HERE/name).open('x',encoding='utf-8',newline='\n') as s:
        json.dump(value,s,indent=2,allow_nan=False); s.write('\n')
def git(*args): return subprocess.check_output(['git','-C',str(ROOT),*args])
def require(condition, message):
    if not condition: raise AssertionError(message)
def check_identity(p, record):
    actual = identity(p)
    require(actual['sha256']==record['sha256'] and actual['bytes']==record['bytes'],str(p))
    return actual
def parse_job(p):
    rows = [shlex.split(line) for line in Path(p).read_text().splitlines()]
    require(len(rows)==9,'job has nine records')
    require(list(map(int,rows[0][:8]))==[128,80,64,2,32,0,1,0],'job dimensions/signals/tuning')
    require(Path(rows[0][8])==DLL,'job exact DLL')
    require([int(r[1]) for r in rows[1:8]]==FORMATS,'formats')
    require([int(r[2]) for r in rows[1:8]]==UPLOADS,'upload frame counts')
    return rows
def load_lobe(p):
    require(Path(p).stat().st_size==PIXELS*8,'FP16 raw lobe byte count')
    return np.fromfile(p,dtype='<f2').reshape(64,80,128,4)

def metrics(a,b):
    # Independent uint16 comparison distinguishes signed-zero and other bit patterns.
    ua=a.view('<u2'); ub=b.view('<u2')
    result={'bytes_exact':bool(np.array_equal(ua,ub)),
            'all_finite':bool(np.isfinite(a).all() and np.isfinite(b).all()),
            'RGB_bits_exact':bool(np.array_equal(ua[...,:3],ub[...,:3])),
            'alpha_bits_exact':bool(np.array_equal(ua[...,3],ub[...,3])),
            'changed_RGB_bit_components':int(np.count_nonzero(ua[...,:3]!=ub[...,:3]))}
    for channels,label in [(slice(0,3),'RGB'),(slice(3,4),'alpha'),(slice(None),'RGBA')]:
        d=a[...,channels].astype(np.float64)-b[...,channels].astype(np.float64)
        result[label]={'rms':float(np.sqrt(np.mean(np.square(d)))),
                       'max_abs':float(np.max(np.abs(d))),
                       'changed_fraction':float(np.count_nonzero(d)/d.size),
                       'per_frame_rms':np.sqrt(np.mean(np.square(d),axis=(1,2,3))).tolist()}
    return result

def source_audit():
    require(sha(ORIGINAL)==SHAS['original'],'original runner pinned')
    require(sha(WORK/'fsrd_rr_output_init.cpp')==SHAS['source'],'new source pinned')
    require(sha(WORK/'fsrd_rr_output_init.exe')==SHAS['exe'],'new EXE pinned')
    require(sha(DLL)==SHAS['dll'],'DLL pinned')
    old=ORIGINAL.read_text(); generated=old
    mappings=[]
    for token in ('api/include/ffx_api_loader.h','api/include/dx12/ffx_api_dx12.h','denoisers/include/ffx_denoiser.h'):
        before='../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/'+token
        after=(ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX'/token).as_posix()
        require(generated.count(before)==1,'unique include')
        generated=generated.replace(before,after); mappings.append({'from':before,'to':after})
    # Read literal strings from prepare.py AST without executing any producer code.
    tree=ast.parse((WORK/'prepare.py').read_text())
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    vals={}; transformations=[]
    for n in main.body:
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
            key=n.targets[0].id
            if key in ('old','new','anchor','block') and isinstance(n.value,ast.Constant):
                vals[key]=n.value.value
                if key=='new': transformations.append(('replace',vals['old'],vals['new']))
                if key=='block': transformations.append(('insert',vals['anchor'],vals['block']))
    require(len(transformations)==3,'three source insertion whitelist operations')
    require([x[0] for x in transformations]==['replace','insert','insert'],'operation kinds')
    require(transformations[0][1]=='if(argc!=2) throw std::runtime_error("usage: fsrd_rr_runner job.txt");','argument replacement anchor')
    require(transformations[1][1]=='    std::string diffOut,specOut; job>>std::quoted(diffOut)>>std::quoted(specOut);','heap insertion anchor')
    require(transformations[2][1]=='        ff(api.Dispatch(&context,&dispatch.header),"dispatch RR");','dispatch insertion anchor')
    for kind,anchor,block in transformations:
        require(generated.count(anchor)==1,'unique insertion anchor')
        generated=generated.replace(anchor,block if kind=='replace' else block+anchor)
    actual=(WORK/'fsrd_rr_output_init.cpp').read_bytes()
    expected=generated.replace('\n','\r\n').encode()
    require(expected==actual,'exact original + whitelisted transformations byte reconstruction')
    diff=''.join(difflib.unified_diff(old.splitlines(keepends=True),generated.splitlines(keepends=True),fromfile='original',tofile='isolated_C'))
    with (HERE/'source_whitelist.diff').open('x',encoding='utf-8',newline='\n') as s: s.write(diff)
    heap=transformations[1][2]; dispatch=transformations[2][2]
    required_heap=['if(outputInitMode)', 'hd.NumDescriptors=2',
                   'hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE',
                   'hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_NONE',
                   'ud.Format=tex[7+j].format','ud.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D',
                   'dev->CreateUnorderedAccessView(tex[7+j].tex.Get(),nullptr,&ud,c)',
                   'dev->CopyDescriptorsSimple(1,v,c,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV)']
    required_dispatch=['if(outputInitMode)', 'cmd->SetDescriptorHeaps(1,heaps)',
                       'clearCPU->GetCPUDescriptorHandleForHeapStart()',
                       'clearVisible->GetGPUDescriptorHandleForHeapStart()',
                       'g.ptr+=UINT64(j)*clearStride','c.ptr+=SIZE_T(j)*clearStride',
                       'cmd->ClearUnorderedAccessViewFloat(g,c,tex[7+j].tex.Get(),value,0,nullptr)',
                       'ub.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV','ub.UAV.pResource=tex[7+j].tex.Get()',
                       'cmd->ResourceBarrier(1,&ub)',
                       'bool clearNow=(outputInitMode==2||outputInitMode==4)?frame==0:(outputInitMode==3||outputInitMode==5)',
                       'const float zero[4]={0,0,0,0};const float sentinel[4]={257,513,769,17}',
                       'const float* value=outputInitMode>=4?sentinel:zero']
    for token in required_heap: require(token in heap,'heap semantics: '+token)
    for token in required_dispatch: require(token in dispatch,'dispatch semantics: '+token)
    require('t.state=i>=7?D3D12_RESOURCE_STATE_UNORDERED_ACCESS' in old,'output initial UAV state')
    require('barrier(t,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);' in old,'after readback restored UAV')
    require(dispatch.index('ClearUnorderedAccessViewFloat')<dispatch.index('cmd->ResourceBarrier'),'clear before UAV barrier')
    modes=[]
    for mode in range(6):
        clear_frames=[] if mode<2 else [0] if mode in (2,4) else list(range(64))
        modes.append({'mode':mode,'heaps_created':2 if mode else 0,
                      'bound_heap_frames':64 if mode else 0,'UAV_barriers':128 if mode else 0,
                      'clear_frames':clear_frames,'clear_calls':2*len(clear_frames),
                      'clear_value_RGBA':None if mode<2 else [257,513,769,17] if mode>=4 else [0,0,0,0]})
    return {'exact_reconstruction':True,'include_mappings':mappings,
            'whitelist_operations':3,'modes':modes,'handles_and_resource_states_checked':True,
            'mode0_qualification':'Logical legacy output lifecycle: no diagnostic heaps, heap binding, clears or UAV barriers. The copied runner still adds argument/log handling, empty ComPtr locals, and an unconditional descriptor-stride query; it is not the old binary.',
            'binary_source_qualification':'Retained build command/log and binary are authenticated; this audit did not rebuild or independently prove machine-code correspondence.'}

def main():
    require(git('branch','--show-current').decode().strip()=='ffxD-experimental-alpha','branch')
    require(git('rev-parse','HEAD').decode().strip()==HEAD,'exact HEAD')
    require(not (HERE/'audit.json').exists(),'preserve completed audit')
    original_freeze=readj(WORK/'pre_native_freeze.json')
    baseline_files=[Path(p) for p in original_freeze['sources']]
    baseline_files += [BASE/'runner.log',ROOT/'tools_tmp/verify_native_output_initialization_stage_20260930.py',
                       ROOT/'tools_tmp/verify_native_output_initialization_stage_v2_20260930.py',
                       ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile/FSRDOutputComp.hlsl']
    baseline_files=list(dict.fromkeys(baseline_files))
    supplement=[identity(p) for p in baseline_files]
    save('baseline_pre_freeze.json',{'schema':'audit-baseline-pre-freeze-v1','files':supplement})
    for p,expected in original_freeze['sources'].items(): require(sha(p)==expected,'original registered source '+p)
    freeze=readj(HERE/'pre_audit_freeze.json')['files']
    for item in freeze: check_identity(item['path'],item)
    result={'schema':'native-output-initialization-independent-audit-v1','utc':datetime.now(timezone.utc).isoformat(),
            'branch':'ffxD-experimental-alpha','head':HEAD,'new_native_contexts':0,'new_native_RR_calls':0,
            'source':source_audit(),'checks':{},'contexts':{},'comparisons':{},'limits':readj(HERE/'preregistration.json')['acceptance_limits']}
    reg=readj(WORK/'registration.json'); producer=readj(WORK/'evidence/results.json'); summary=readj(WORK/'output_completeness_summary.json')
    require(sha(WORK/'output_completeness_summary.json')==SHAS['summary'],'summary pinned')
    require(reg['mode_order']==TAGS and original_freeze['variants']==TAGS,'registered order')
    require(producer['status']=='completed_native_diagnostic_not_solution','producer completion status')
    require(producer['completed_native_contexts']==12 and producer['native_RR_calls']==768,'counts')
    require(producer['quality_accepted'] is False and producer['game_run'] is False,'limits declared')
    require(summary['report_sha256']==sha(WORK/'evidence/results.json'),'summary pins producer report')
    require(producer['pre_native_freeze_sha256']==sha(WORK/'pre_native_freeze.json'),'report pins pre-native registration')
    require(len(producer['rows'])==1 and producer['rows'][0]['case']=='wave','one wave case')
    row=producer['rows'][0]; require(list(row['contexts'])==TAGS,'report order')
    run_lines=(WORK/'run.log').read_text().splitlines()
    require(run_lines[:12]==['wave '+tag+' completed' for tag in TAGS],'completion log forward/reverse order')
    baseline_rows=parse_job(BASE/'job.txt')
    baseline_inputs={f'input{i}.bin':sha(BASE/f'input{i}.bin') for i in range(7)}
    base_controls=(BASE/'dispatch_controls.bin').read_bytes()
    require(len(base_controls)==64*184,'baseline exact 184-byte controls')
    input_details=[]
    for i,(fmt,count) in enumerate(zip(FORMATS,UPLOADS)):
        p=BASE/f'input{i}.bin'; bpp=8 if fmt==10 else 4
        require(p.stat().st_size==128*80*bpp*count,'input size format')
        input_details.append({'index':i,'DXGI_format':fmt,'upload_frames':count,'bytes':p.stat().st_size,'sha256':sha(p)})
    ctrl=[]
    for frame in range(64):
        record=base_controls[frame*184:(frame+1)*184]
        f,flags,w,h=struct.unpack_from('<4I',record,0)
        motion=struct.unpack_from('<3f',record,16); camera=struct.unpack_from('<3f',record,28)
        jitter=struct.unpack_from('<2f',record,40); depth=struct.unpack_from('<2f',record,48)
        view=struct.unpack_from('<16f',record,56); projection=struct.unpack_from('<16f',record,120)
        require([f,flags,w,h]==[frame,3 if frame==0 else 2,128,80],'applied frame/flags/dimensions')
        require(motion==(1,1,1) and camera==(0,0,0) and jitter==(0,0) and depth==(0,1024),'applied scalar controls')
        require(view==tuple(float(i in (0,5,10,15)) for i in range(16)),'identity view')
        require(all(np.isfinite(projection)),'finite projection')
        if frame: require(record[16:]==base_controls[16:184],'all other controls constant')
        ctrl.append({'frame':f,'flags':flags,'render_size':[w,h]})
    frame_lines=(BASE/'frame_controls.txt').read_text().splitlines()
    require([list(map(float,line.split())) for line in frame_lines]==[[1,0,0]]+[[0,0,0]]*63,'serialized frame controls')
    base_log=(BASE/'runner.log').read_text()
    provider_line=next(x for x in base_log.splitlines() if x.startswith('provider='))
    adapter_line=next(x for x in base_log.splitlines() if x.startswith('adapter='))
    arrays={}; pids=[]; guards=[]; sentinel=np.array([257,513,769,17],dtype='<f2')
    require(sentinel.astype(np.float64).tolist()==[257,513,769,17],'FP16 exact sentinel')
    sentinel_total=0
    for tag in TAGS:
        folder=WORK/'evidence/wave'/tag; rows=parse_job(folder/'job.txt'); mode=int(tag[-1])
        require(not (folder/'camera.txt').exists() and not (BASE/'camera.txt').exists(),'no camera override')
        require([r[1:] for r in rows[1:8]]==[r[1:] for r in baseline_rows[1:8]],'formats and uploads match baseline')
        for i,r in enumerate(rows[1:8]):
            p=folder/f'input{i}.bin'
            require(Path(r[0])==p,'job raw input path')
            require(p.read_bytes()==(BASE/f'input{i}.bin').read_bytes(),'all serialized input bytes exact')
        require([Path(x) for x in rows[8]]==[folder/n for n in LOBES],'output job paths')
        require(readj(folder/'amd_input_identity.json')==baseline_inputs,'input identity JSON')
        require((folder/'dispatch_controls.bin').read_bytes()==base_controls,'all applied controls exact')
        require((folder/'frame_controls.txt').read_bytes()==(BASE/'frame_controls.txt').read_bytes(),'frame control text exact')
        identity_json=readj(folder/'amd_context_identity.json')
        require(identity_json==row['contexts'][tag],'report/context identity exact')
        require(identity_json['inputs']==baseline_inputs,'report seven inputs exact')
        require(identity_json['runner_sha256']==SHAS['exe'] and identity_json['dll_sha256']==SHAS['dll'],'runtime identity pin')
        require(identity_json['applied_dispatch_sha256']==sha(BASE/'dispatch_controls.bin'),'dispatch SHA')
        guard=readj(folder/'resource_guard.json'); guard_args=guard['args']
        require([Path(x) for x in guard_args[:2]]==[WORK/'fsrd_rr_output_init.exe',folder/'job.txt'] and guard_args[2]==str(mode),'owned child exact executable/job/mode')
        require(guard['timeout_seconds']==240 and guard['maximum_working_set_bytes']==2*1024**3 and guard['minimum_available_memory_bytes']==1024**3,'unchanged guard bounds')
        require(guard['status']=='completed' and guard['returncode']==0 and guard['terminated_owned_child'] is False and guard['termination_reason'] is None,'guard completion')
        require(guard['elapsed_seconds']<240 and guard['peak_observed_working_set_bytes']<=2*1024**3 and guard['minimum_observed_available_bytes']>=1024**3,'observed guard range')
        require(guard['samples']>0 and guard['sample_interval_seconds']==.2,'guard samples')
        pids.append(guard['child_pid']); guards.append(guard)
        stdout=(folder/'stdout.log').read_bytes(); stderr=(folder/'stderr.log').read_bytes()
        require((folder/'runner.log').read_bytes()==stdout+stderr,'combined log serialization')
        log=(stdout+stderr).decode()
        require(f'output_initialization_mode={mode}\n' in log.replace('\r\n','\n'),'reported mode')
        require(provider_line in log and adapter_line in log,'provider/adapter match previous B')
        require('dll='+str(DLL) in log,'loaded exact DLL path')
        require('dispatches=64' in log and 'debug_layer=1' in log,'dispatch/debug markers')
        for field in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'):
            require(re.search(r'\b'+field+r'=0\b',log) is not None,'ordinary zero count '+field)
        require(stderr==b'','empty ordinary stderr')
        outputs={}; arrays[tag]={}
        for name in LOBES:
            p=folder/name; require(identity_json['outputs'][name]==sha(p),'raw output SHA')
            a=load_lobe(p); arrays[tag][name]=a
            require(np.isfinite(a).all(),'all RGBA finite')
            counts=np.count_nonzero(a==sentinel,axis=(0,1,2)).tolist()
            per_frame=np.count_nonzero(a==sentinel,axis=(1,2)).tolist()
            require(counts[:3]==[0,0,0],'no retained sentinel RGB component')
            require(np.all(a[...,3]==(17 if mode>=4 else 0)),'alpha expected throughout 64 frames')
            require(counts[3]==PIXELS if mode>=4 else counts[3]==0,'alpha sentinel counts')
            sentinel_total+=sum(counts)
            independent={'sha256':sha(p),'minimum_RGBA':a.min(axis=(0,1,2)).astype(float).tolist(),
                         'maximum_RGBA':a.max(axis=(0,1,2)).astype(float).tolist(),
                         'sentinel_matches_RGBA':counts,'output_alpha_all_zero':bool(np.all(a[...,3]==0)),'finite':True}
            require(independent==summary['modes'][tag][name],'summary per-lobe values independently match')
            signal_i=5 if name=='diffuse.bin' else 6
            signal=load_lobe(folder/f'input{signal_i}.bin')
            outputs[name]={**independent,'bytes':p.stat().st_size,'per_frame_sentinel_matches_RGBA':per_frame,
                           'input_alpha_min':float(signal[...,3].min()),'input_alpha_max':float(signal[...,3].max()),
                           'output_equals_input_alpha_fraction':float(np.mean(a[...,3]==signal[...,3]))}
        result['contexts'][tag]={'mode':mode,'guard':guard,'outputs':outputs,'applied_control_records':64,'raw_inputs_exact':7}
    require(len(set(pids))==12,'twelve distinct retained child PIDs')
    require(sentinel_total==5242880 and summary['all_sentinel_component_matches']==sentinel_total,'sentinel total')
    require(len(row['comparisons'])==66,'66 pair comparisons')
    repeat_keys=[]; exact_pairs=0; mixed_pairs=0
    for left,right in itertools.combinations(TAGS,2):
        key=left+'__'+right; pair={}
        for name in LOBES:
            m=metrics(arrays[left][name],arrays[right][name]); pair[name]=m
            stored=row['comparisons'][key][name]
            require({k:v for k,v in m.items() if k in stored}==stored,'independent raw metrics '+key+' '+name)
            require(m['RGB_bits_exact'] and m['RGB']['rms']==0,'all pair raw RGB bits')
        result['comparisons'][key]=pair
        if all(m['bytes_exact'] for m in pair.values()): exact_pairs+=1
        else: mixed_pairs+=1
        if left[-1]==right[-1]:
            require(all(m['bytes_exact'] for m in pair.values()),'repeat raw exact')
            repeat_keys.append(key)
    require(exact_pairs==34 and mixed_pairs==32 and len(repeat_keys)==6,'pair group counts')
    require(producer['all_ablation_pairs_raw_outputs_exact'] is False,'alpha difference flag faithfully false')
    default_vs_old={}
    for name in LOBES:
        m=metrics(arrays['round0_mode0'][name],load_lobe(BASE/name)); default_vs_old[name]=m
        require({k:v for k,v in m.items() if k in row['fresh_original_vs_previous'][name]}==row['fresh_original_vs_previous'][name],'mode0 previous comparison metrics')
        require(m['bytes_exact'],'mode0 raw exact vs B')
    result['default_C0_vs_old_B']=default_vs_old
    result['controls']={'layout_bytes':184,'total_bytes_per_context':len(base_controls),'view_offset':56,'projection_offset':120,
                        'flags':{'frame0':3,'frames1_to63':2},'motion_scale':[1,1,1],'camera_delta':[0,0,0],
                        'jitter':[0,0],'depth_bounds':[0,1024],'view':list(view),'projection':list(projection),
                        'sha256':sha(BASE/'dispatch_controls.bin'),'records':ctrl}
    result['inputs']=input_details
    result['provider']={'dll':identity(DLL),'logged_adapter':adapter_line,'logged_provider':provider_line,
                        'qualification':'Provider name/id version query is unavailable (id 0, result 6). The directly loaded DLL path/hash and requested API 4202496 match; do not claim a successful provider-version query.'}
    manifest=readj(ARCHIVE/'manifest.json'); require(sha(ARCHIVE/'manifest.json')==SHAS['manifest'],'archive manifest pinned')
    require(len(manifest['copied_files'])==manifest['copied_file_count']==131,'131 copied files')
    require(len(manifest['retained_external_payloads'])==112,'112 external payloads')
    for item in manifest['copied_files']:
        check_identity(ARCHIVE/item['archive'],item); check_identity(item['source'],item)
    for item in manifest['retained_external_payloads']: check_identity(item['source'],item)
    expected=sorted([p.relative_to(ROOT).as_posix() for p in ARCHIVE.rglob('*') if p.is_file()]+[
        'docs/fsrd_native_output_initialization.md','docs/evidence/fsrd_native_output_initialization_rgb_bit_proof.json','docs/evidence/.gitattributes'])
    committed=git('diff-tree','--no-commit-id','--name-only','-r','-z',HEAD).decode().split('\0')[:-1]
    require(sorted(committed)==expected and len(expected)==136,'136 committed doc/evidence files')
    for name in expected:
        require(git('show',HEAD+':'+name)==(ROOT/name).read_bytes(),'current HEAD exact archive/doc byte '+name)
    require(git('show',HEAD+':'+ORIGINAL.relative_to(ROOT).as_posix())==ORIGINAL.read_bytes(),'original source untouched in HEAD')
    require((ARCHIVE/'.gitattributes').read_bytes()==b'* -text\r\n','archive byte attribute')
    attr=git('check-attr','text','--','docs/evidence/fsrd_native_output_initialization_rgb_bit_proof.json').decode().strip()
    require(attr.endswith(': unset'),'standalone proof exact filename byte rule')
    erratum=readj(ROOT/'tools_tmp/native_output_initialization_stage_erratum_20260930.json')
    require(sha(ROOT/'tools_tmp/verify_native_output_initialization_stage_20260930.py')==erratum['initial_verifier_sha256'],'initial verifier pinned')
    stage_v2=readj(ROOT/'tools_tmp/native_output_initialization_staged_verification_v2_20260930.json')
    require(stage_v2['status']=='passed_exact_stage_and_external_payload_bytes' and stage_v2['staged_files']==136 and stage_v2['external_payloads']==112,'retained corrected stage verifier result')
    result['archive']={'manifest':identity(ARCHIVE/'manifest.json'),'copied_source_and_archive_files_verified':131,
                       'external_payloads_verified':112,'committed_byte_exact_files_verified':136,'check_attr':attr,
                       'historical_initial_verifier_erratum':erratum,
                       'historical_qualification':'The retained erratum reports the initial standalone JSON CRLF normalization failure and exact-filename -text correction. No initial console failure log was supplied. This audit independently proves current committed bytes, not the past failed index state.',
                       'corrected_stage_record':stage_v2}
    header=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h'
    require(header.read_text().count('output: Preserved (or input if passthrough)')==4,'SDK header preserved wording')
    shader=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile/FSRDOutputComp.hlsl'
    text=shader.read_text()
    raw_lines=[{'line':i,'text':s.strip()} for i,s in enumerate(text.splitlines(),1) if 'FLAGS_RAW_SOURCE_BLIT' in s or 'OutColor[p]' in s or 'InDiff' in s and '.rgb' in s or 'InSpec' in s and '.rgb' in s]
    result['contract']={'header':identity(header),'documented_preserved_occurrences':4,
                        'empirical_destination_alpha_retained':True,
                        'same_value_write_and_no_write_indistinguishable':True,
                        'input_alpha_copy_not_observed':all(v['output_equals_input_alpha_fraction']==0 for c in result['contexts'].values() for v in c['outputs'].values()),
                        'ordinary_composition_source':identity(shader),'source_reference_lines':raw_lines,
                        'qualification':'Header alpha wording does not by itself disambiguate input versus destination preservation. Composition inspection concerns the existing shader path only; no new composition GPU execution or universal consumer claim.'}
    result['checks']={'status':'passed_with_qualifications','native_contexts_verified':12,'RR_dispatches_verified':768,
                      'distinct_child_pids':12,'all_66_pairs_metrics_match_producer':True,
                      'raw_lobe_comparisons_verified':132,'all_12_RGB_bits_exact':True,'all_6_repeats_RGBA_bytes_exact':True,
                      'RGBA_exact_pairs':34,'alpha_different_pairs':32,'all_24_lobes_finite':True,
                      'sentinel_RGB_component_matches':0,'sentinel_alpha_matches':sentinel_total,
                      'sentinel_contexts':4,'sentinel_lobes':8,'sentinel_alpha_matches_per_lobe':PIXELS,
                      'all_8_other_contexts_alpha_zero':True,'mode0_vs_previous_B_both_lobes_RGBA_exact':True,
                      'ordinary_errors_and_warnings_all_zero':True,
                      'observed_guard_elapsed_seconds_range':[min(g['elapsed_seconds'] for g in guards),max(g['elapsed_seconds'] for g in guards)],
                      'observed_guard_peak_working_set_max':max(g['peak_observed_working_set_bytes'] for g in guards),
                      'observed_guard_available_memory_min':min(g['minimum_observed_available_bytes'] for g in guards),
                      'archive_copied_verified':131,'archive_external_verified':112,'committed_file_bytes_verified':136}
    post=[]
    for item in freeze+supplement: post.append(check_identity(item['path'],item))
    require(git('rev-parse','HEAD').decode().strip()==HEAD,'HEAD unchanged after audit')
    save('post_audit_freeze.json',{'schema':'independent-audit-post-freeze-v1','all_unchanged':True,'files':post})
    result['freeze']={'working_archive_pre_freeze_files':len(freeze),'baseline_pre_freeze_files':len(supplement),
                      'all_source_reports_archive_payloads_unchanged':True,
                      'pre_freeze':identity(HERE/'pre_audit_freeze.json'),'baseline_pre_freeze':identity(HERE/'baseline_pre_freeze.json'),
                      'post_freeze':identity(HERE/'post_audit_freeze.json')}
    save('audit.json',result)
    compact={'schema':'native-output-initialization-independent-compact-v1','head':HEAD,'audit':identity(HERE/'audit.json'),
             'checks':result['checks'],'new_native_contexts':0,'new_native_RR_calls':0,'quality_accepted':False,
             'conclusion':'All twelve raw RGB bit sequences and all six within-mode raw RGBA repeat pairs match. Four sentinel contexts retain destination alpha 17 in both lobes throughout all 64 frames. The raw alpha evidence cannot establish no write versus same-value write or a general provider contract, and this control has no observed RGB effect for the one frozen wave input.',
             'qualifications':[result['source']['mode0_qualification'],result['source']['binary_source_qualification'],
                               result['provider']['qualification'],result['archive']['historical_qualification'],*result['limits']]}
    save('compact.json',compact)
    qualification='Independent output initialization audit: passed with qualifications.\n\n'
    qualification+='Verified 12 distinct retained child processes, 64 dispatches each, 768 total; no new native/GPU/game/build jobs. All 66 pair comparisons (132 lobes) reproduce the producer metrics. Raw uint16 RGB bits agree for all 12 contexts; all 6 repeat pairs are exact RGBA. There are 34 RGBA-exact pairs and 32 pairs differing only in alpha. Sentinel modes 4/5 in both rounds retain alpha 17 at all 655,360 pixels per lobe (8 lobes; 5,242,880 alpha matches). All other alpha values are zero; no sentinel RGB component survives; all 24 lobes are finite. C mode0 matches previous B raw RGBA for both frozen wave lobes.\n\n'
    qualification+='Authenticated all 7 input byte strings/formats/upload counts, 64 applied 184-byte records per context (view 56, projection 120; flags 3 then 2; 128x80), exact DLL path/hash, resource guards at 240 seconds / 2 GiB child working set / 1 GiB available, and ordinary error/warning counts of zero. Source is exactly reconstructed from the untouched original using three include maps and three whitelisted insertion operations. The clear handles reference matching CPU nonvisible and GPU visible UAV descriptors for the same FP16 resource; pre-dispatch barriers follow the clear and output state remains UAV at each dispatch.\n\n'
    qualification+='Verified 131 copied source/archive pairs, 112 external payloads, and all 136 current HEAD document/evidence blob byte strings. The initial CRLF normalization failure remains qualified by the retained erratum; there is no initial failure console log to authenticate. The exact-filename -text rule and current committed bytes are verified. All preregistered working reports/payloads and baseline evidence are SHA/size unchanged after the audit.\n\n'
    qualification+='The experiment establishes empirical destination-alpha retention for this input. It cannot distinguish no store from a same-value store, rule out transient reads/internal-state problems, establish a universal SDK alpha contract, or explain game RGB stains/waves. Provider-version querying is unavailable despite authenticated direct DLL loading. Mode0 is logically the legacy output lifecycle, with added diagnostic argument/log/local/stride-query code. Retained build evidence authenticates provenance but this audit did not rebuild. No quality result or production acceptance is inferred.\n'
    with (HERE/'qualification.txt').open('x',encoding='utf-8',newline='\n') as s: s.write(qualification)
    files=[identity(p) for p in sorted(HERE.iterdir()) if p.is_file()]
    save('completion_manifest.json',{'schema':'immutable-independent-audit-completion-v1','status':'completed_passed_with_qualifications',
                                    'head':HEAD,'new_native_contexts':0,'new_native_RR_calls':0,'quality_accepted':False,
                                    'files':files,'working_reports_unchanged':True})
    print(json.dumps({'status':'completed_passed_with_qualifications','checks':result['checks'],
                      'compact':identity(HERE/'compact.json'),'completion_manifest':identity(HERE/'completion_manifest.json')}))

if __name__=='__main__': main()
