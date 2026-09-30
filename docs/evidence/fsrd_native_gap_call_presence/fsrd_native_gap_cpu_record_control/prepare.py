"""Matched missing-GPU-frame control preparation. Compile only; never run native."""
from pathlib import Path
from datetime import datetime,timezone
import difflib,hashlib,json,os,shlex,shutil,struct,subprocess,sys
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha');HERE=Path(__file__).resolve().parent
PRIOR=ROOT/'tools_tmp/fsrd_native_discarded_recording_diagnostic_20260930'
SOURCE=ROOT/'tools_tmp/native_continuous_harmonic_remaining_20260930/evidence/wave/harmonic_pilot'
DLL=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
KINDS=('record_discard24','no_api24','record_discard24_reset25','no_api24_reset25')
ORDER=[f'round0_{k}'for k in KINDS]+[f'round1_{k}'for k in reversed(KINDS)]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,v):
    with Path(p).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def write(p,t):
    with Path(p).open('x',encoding='utf-8',newline='\n')as f:f.write(t)
def main():
    assert not(HERE/'registration.json').exists()and not(HERE/'fsrd_rr_gap_control.cpp').exists(),'Preserve preparation attempts'
    base=PRIOR/'fsrd_rr_discard.cpp';assert sha(base)=='5446243c4a7b18f94254f1b1098313102da9d601ee4dcec6433eb3a36993207c'
    assert sha(PRIOR/'execution_completion_manifest.json')=='8baca7561be8e9569bb222182aa85ee2a61bd518989f7fa17a955af588ba68d8'
    assert sha(DLL)=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
    text=base.read_text();changes=[]
    def replace(before,after,label):
        nonlocal text
        assert text.count(before)==1,label;text=text.replace(before,after);changes.append({'label':label,'before':before,'after':after})
    replace('if(argc<2||argc>5) throw std::runtime_error("usage: fsrd_rr_discard job.txt [skip_frame=-1] [recovery_reset_frame=-1] [source_frame_start=0]");',
        'if(argc<2||argc>6) throw std::runtime_error("usage: fsrd_rr_gap_control job.txt [skip_frame=-1] [recovery_reset_frame=-1] [source_frame_start=0] [no_api_frame=-1]");','optional_no_API_argument')
    replace('    if(skipFrame < -1 || recoveryResetFrame < -1 || sourceFrameStart>63) throw std::runtime_error("invalid diagnostic frame arguments");',
'''    const int noApiFrame=argc>=6?std::stoi(argv[5]):-1;
    if(skipFrame < -1 || recoveryResetFrame < -1 || sourceFrameStart>63 || noApiFrame < -1 || (skipFrame>=0 && noApiFrame>=0))
        throw std::runtime_error("invalid or competing diagnostic frame arguments");''','no_API_argument_validation')
    replace('    std::cout<<"skip_frame="<<skipFrame<<" recovery_reset_frame="<<recoveryResetFrame<<" source_frame_start="<<sourceFrameStart<<\'\\n\';',
        '    std::cout<<"skip_frame="<<skipFrame<<" recovery_reset_frame="<<recoveryResetFrame<<" source_frame_start="<<sourceFrameStart<<" no_api_frame="<<noApiFrame<<\'\\n\';','registered_argument_log')
    replace('        throw std::runtime_error("diagnostic source frame outside job");',
'''        throw std::runtime_error("diagnostic source frame outside job");
    if(noApiFrame>=0 && (unsigned(noApiFrame)<sourceFrameStart || unsigned(noApiFrame)>=sourceFrameStart+frames))
        throw std::runtime_error("no-API source frame outside job");''','no_API_frame_range')
    replace('    unsigned successfulRecordings=0,queuedDispatches=0,discardedRecordings=0;',
'''    std::ofstream omittedAPIFrameIndicesOut(std::filesystem::path(argv[1]).parent_path()/"omitted_API_frame_indices.bin",std::ios::binary);
    if(!omittedAPIFrameIndicesOut) throw std::runtime_error("omitted API indices output open");
    unsigned successfulRecordings=0,queuedDispatches=0,discardedRecordings=0,omittedAPIRecordings=0;''','separate_actual_omission_metadata')
    replace('        auto record=[&](const auto& value) { controlsOut.write(reinterpret_cast<const char*>(&value),sizeof(value)); };',
'''        if(noApiFrame>=0 && sourceFrame==unsigned(noApiFrame)) {
            // Inputs, transitions, and frame controls were consumed normally.
            // Deliberately omit the SDK API call and its applied-control packet.
            // Both arms abandon frame24 GPU work after completed sourceframe23.
            if(previousSubmittedSourceFrame!=int(sourceFrame)-1 || previousCompletedFence==0)
                throw std::runtime_error("no-API omission requires completed immediately prior submission");
            hr(cmd->Close(),"close no-API discarded recording");
            for(unsigned i=0;i<9;++i) tex[i].state=externalStatesBeforeRecording[i];
            const char absent=0; presenceOut.write(&absent,1); ++omittedAPIRecordings;
            omittedAPIFrameIndicesOut.write(reinterpret_cast<const char*>(&sourceFrame),sizeof(sourceFrame));
            std::cout<<"omitted_API_recording source_frame="<<sourceFrame<<" previous_submitted_source_frame="<<previousSubmittedSourceFrame
                     <<" previous_completed_fence="<<previousCompletedFence<<" external_state_shadow_restored=1 API_called=0 queued=0 observed_output=0\\n";
            continue;
        }
        auto record=[&](const auto& value) { controlsOut.write(reinterpret_cast<const char*>(&value),sizeof(value)); };''','no_API_branch_after_inputs_controls_before_applied_packet_and_API')
    replace('    if(!presenceOut||!frameIndicesOut||!recordedFrameIndicesOut) throw std::runtime_error("presence/index output write");',
'''    if(!presenceOut||!frameIndicesOut||!recordedFrameIndicesOut) throw std::runtime_error("presence/index output write");
    omittedAPIFrameIndicesOut.close(); if(!omittedAPIFrameIndicesOut) throw std::runtime_error("omitted API indices output write");''','close_omission_metadata')
    replace('<<" sdk_errors="<<sdkErrors<<" sdk_warnings="<<sdkWarnings<<\'\\n\';',
        '<<" sdk_errors="<<sdkErrors<<" sdk_warnings="<<sdkWarnings<<" no_API_omissions="<<omittedAPIRecordings<<\'\\n\';','direct_footer_omission_counter')
    cpp=HERE/'fsrd_rr_gap_control.cpp';write(cpp,text);shutil.copyfile(base,HERE/'copied_pinned_H2_runner.cpp')
    save(HERE/'source_insertion_whitelist.json',{'pinned_H2_source':identity(base),'prior_original_runner':identity(ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_rr_runner.cpp'),'new_source':identity(cpp),'operations':changes,
        'absolute_include_mapping':'Inherited byte-exact from pinned H2 source; no SDK includes changed by this diagnostic.'})
    write(HERE/'source_insertion_whitelist.diff',''.join(difflib.unified_diff(base.read_text().splitlines(keepends=True),text.splitlines(keepends=True),fromfile='pinned_H2_runner',tofile='isolated_matched_gap_runner')))
    guard=PRIOR/'native_resource_guard.py';assert sha(guard)=='b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814';shutil.copyfile(guard,HERE/'native_resource_guard.py')
    SDK=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX'
    headers=[SDK/p for p in('api/include/ffx_api_loader.h','api/include/dx12/ffx_api_dx12.h','denoisers/include/ffx_denoiser.h','api/include/ffx_api.h','api/include/ffx_api_types.h')]
    header_before=[identity(p)for p in headers]
    os.environ['TEMP']=str(ROOT/'tools_tmp/native_compile_temp_20260930');os.environ['TMP']=os.environ['TEMP'];assert Path(os.environ['TEMP']).is_dir()
    buildargs=[sys.executable,str(HERE/'build_runner.py')];save(HERE/'build_command.json',{'args':buildargs,'TEMP':os.environ['TEMP'],'TMP':os.environ['TMP']})
    built=subprocess.run(buildargs,cwd=HERE,capture_output=True);(HERE/'build.stdout.bin').write_bytes(built.stdout);(HERE/'build.stderr.bin').write_bytes(built.stderr)
    save(HERE/'build_result.json',{'returncode':built.returncode,'stdout':identity(HERE/'build.stdout.bin'),'stderr':identity(HERE/'build.stderr.bin'),'new_native_contexts':0})
    assert built.returncode==0,'Preserve failed build attempt; no native work ran'
    assert header_before==[identity(p)for p in headers]
    rows=[shlex.split(s)for s in(SOURCE/'job.txt').read_text().splitlines()]
    assert len(rows)==9 and list(map(int,rows[0][:8]))==[128,80,64,2,32,0,1,0]and Path(rows[0][8])==DLL
    assert[int(r[1])for r in rows[1:8]]==[41,10,24,28,28,10,10]and[int(r[2])for r in rows[1:8]]==[1,1,1,1,1,64,64]
    previous_identity=json.loads((SOURCE/'amd_context_identity.json').read_text());assert previous_identity['inputs']=={f'input{i}.bin':sha(SOURCE/f'input{i}.bin')for i in range(7)}
    original_controls=(SOURCE/'dispatch_controls.bin').read_bytes();assert previous_identity['applied_dispatch_sha256']==sha(SOURCE/'dispatch_controls.bin')and previous_identity['dll_sha256']==sha(DLL)
    assert len(original_controls)==64*184
    for f in range(64):assert struct.unpack_from('<4I',original_controls,f*184)==(f,3 if f==0 else 2,128,80)
    queued_ids=[f for f in range(64)if f!=24];cases=[]
    for tag in ORDER:
        kind=tag.split('_',1)[1];no_api=kind.startswith('no_api');reset=25 if kind.endswith('_reset25')else-1
        folder=HERE/'evidence'/tag;folder.mkdir(parents=True,exist_ok=False);inputs=[];lines=[]
        for i,row in enumerate(rows[1:8]):
            src=SOURCE/f'input{i}.bin';assert Path(row[0])==src;fmt,uploads=map(int,row[1:]);data=src.read_bytes();assert len(data)==128*80*(8 if fmt==10 else 4)*uploads
            dest=folder/f'input{i}.bin';dest.write_bytes(data);inputs.append({**identity(dest),'index':i,'DXGI_format':fmt,'uploads':uploads,'source':identity(src),'source_frame_start':0,'source_frame_count':uploads})
            lines.append(f'"{dest.as_posix()}" {fmt} {uploads}')
        shutil.copyfile(SOURCE/'frame_controls.txt',folder/'frame_controls.txt')
        if(SOURCE/'camera.txt').exists():shutil.copyfile(SOURCE/'camera.txt',folder/'camera.txt')
        full=bytearray(original_controls)
        if reset==25:struct.pack_into('<I',full,25*184+4,3)
        api_ids=queued_ids if no_api else list(range(64));applied=b''.join(full[f*184:(f+1)*184]for f in api_ids);queued=b''.join(full[f*184:(f+1)*184]for f in queued_ids)
        (folder/'expected_applied_dispatch_controls.bin').write_bytes(applied);(folder/'expected_queued_dispatch_controls.bin').write_bytes(queued)
        presence=bytes(0 if f==24 else 1 for f in range(64));(folder/'expected_output_presence.bin').write_bytes(presence)
        for name,ids in(('expected_recorded_frame_indices.bin',api_ids),('expected_observed_frame_indices.bin',queued_ids),('expected_omitted_API_frame_indices.bin',[24]if no_api else[])):
            (folder/name).write_bytes(struct.pack('<'+str(len(ids))+'I',*ids))
        write(folder/'job.txt','128 80 64 2 32 0 1 0 '+f'"{DLL.as_posix()}"\n'+'\n'.join(lines)+f'\n"{(folder/"diffuse.bin").as_posix()}" "{(folder/"specular.bin").as_posix()}"\n')
        c={'tag':tag,'kind':kind,'loop_frames':64,'frames_recorded':len(api_ids),'frames_queued':63,'frames_discarded':0 if no_api else 1,'frames_omitted_API':1 if no_api else 0,
            'skip_frame':-1 if no_api else 24,'no_api_frame':24 if no_api else-1,'recovery_reset_frame':reset,'source_frame_start':0,
            'source_frame_indices':api_ids,'consumed_source_frame_indices':list(range(64)),'observed_frame_indices':queued_ids,'omitted_API_frame_indices':[24]if no_api else[],
            'output_presence_mask':list(presence),'command':[str(HERE/'fsrd_rr_gap_control.exe'),str(folder/'job.txt'),str(-1 if no_api else 24),str(reset),'0',str(24 if no_api else-1)],
            'inputs':inputs,'expected_raw_lobe_bytes':63*128*80*8,'expected_applied_dispatch_controls':identity(folder/'expected_applied_dispatch_controls.bin'),
            'expected_queued_dispatch_controls':identity(folder/'expected_queued_dispatch_controls.bin'),'expected_output_presence':identity(folder/'expected_output_presence.bin'),
            'expected_recorded_frame_indices':identity(folder/'expected_recorded_frame_indices.bin'),'expected_observed_frame_indices':identity(folder/'expected_observed_frame_indices.bin'),
            'expected_omitted_API_frame_indices':identity(folder/'expected_omitted_API_frame_indices.bin'),'job':identity(folder/'job.txt'),'frame_controls':identity(folder/'frame_controls.txt')}
        cases.append(c)
    assert[sum(c[k]for c in cases)for k in('frames_recorded','frames_queued','frames_discarded','frames_omitted_API')]==[508,504,4,4]
    for reset in(False,True):
        group=[c for c in cases if(c['recovery_reset_frame']==25)==reset]
        assert len({sha(Path(c['expected_queued_dispatch_controls']['path']))for c in group})==1
        for i in range(7):assert len({c['inputs'][i]['sha256']for c in group})==1
    registration={'schema':'matched-GPU-gap-successful-CPU-SDK-record-control-preparation-v1','UTC':datetime.now(timezone.utc).isoformat(),
        'status':'prepared_built_preregistered_NOT_AUTHORIZED_TO_RUN','preparation_only':True,'branch':subprocess.check_output(['git','-C',str(ROOT),'branch','--show-current']).decode().strip(),'head':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD']).decode().strip(),
        'mode_order':ORDER,'cases':cases,'planned_native_contexts':8,'planned_successful_API_RR_recordings':508,'planned_queued_RR_dispatches':504,'planned_discarded_API_RR_recordings':4,'planned_no_API_omissions':4,
        'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0,'actual_no_API_omissions':0,
        'pinned_prior_H2_source':identity(base),'prior_H2_execution_completion_manifest':identity(PRIOR/'execution_completion_manifest.json'),'prior_H2_reference_contexts':8,'prior_H2_reference_contexts_are_new_measurements':False,
        'new_source':identity(cpp),'new_binary':identity(HERE/'fsrd_rr_gap_control.exe'),'dll':identity(DLL),'SDK_headers':header_before,
        'source_frozen_wave_P':str(SOURCE),'source_controls':identity(SOURCE/'dispatch_controls.bin'),'source_previous_context_identity':identity(SOURCE/'amd_context_identity.json'),
        'settings':{'dimensions':[128,80],'loop_frames':64,'diffuse_signal':2,'specular_signal':32,'reset_every':0,'tuning':1,'passthrough':0,'tuning_values':[.1,.5,.5,40000.,40.,.5],'formats':[41,10,24,28,28,10,10],'uploads':[1,1,1,1,1,64,64],'provider_requested_API':4202496},
        'hypothesis':'At matched GPU executed sourceframes0..23,25..63 and identical queued inputs/184-byte controls, compare api.Dispatch24 successfulrecord-then-discard against omission of that API call. Any repeatable later difference is conditional on that call-presence intervention; no specific opaque internal mechanism is assumed.',
        'no_API_branch':'After all usual input reads/uploads/transitions and sourceframe24 control parsing, before applied-control serialization and api.Dispatch, require completed sourceframe23, close abandoned command list, restore9external Tex.state shadows, mark24 absent and omittedAPI marker, continue. Neither SDK record24 nor applied packet24 nor recorded-index24 exists in this arm. Next list/allocator Reset occurs with previous submitted fence already complete.',
        'matching':'All arms consume original inputs0..63 including24; GPU queued sourceframes exclude24 in botharms. Original frameIndex and184-byte queued controls exactly match within reset setting. no-reset25flags2 vsRESET25flags3 is explicit; no API/no omittedzero payload is fabricated.',
        'analysis_plan':{'context_pairs':28,'alignments':['submitted_ordinal (same observedsourceframes in all8arms)','common_source_frame'],'lobes':['diffuse.bin','specular.bin'],
            'metrics':['rawRGB/RGBAuint16bit equality','RGB/RGBA/alpha float64RMS/max/changedscalarfraction','perframeRMS'],'interpretation':'Descriptive observed comparisons and repeats; no quality/truth/oracle threshold. Flag/reset-control mismatch remains annotated.'},
        'stage_count_accounting':'Separate attempted owned child, created context, completed CPP footer, successfulAPI record, completed queued/readback, SDKrecorddiscard, noAPIomission, observed raw output, and metadata acceptance. Valid bounded pinned CPP footer authoritative before acceptance; no validfooter means valid-prefix/capacity lower bounds and unknown totals. Conflicting artifact claims are retained and rejected, never max-merged as exact counts.',
        'guard':{'source_sha256':sha(HERE/'native_resource_guard.py'),'timeout_seconds':240,'maximum_working_set_bytes':2147483648,'minimum_available_memory_bytes':1073741824,'sample_interval_seconds':.2,'policy':'Sequential owned child only; refuse lowRAM; terminate only guard-owned child if needed; never kill other processes.'},
        'build':{'command':identity(HERE/'build_command.json'),'MSVC_command':identity(HERE/'fsrd_rr_gap_control.build.cmd'),'result':identity(HERE/'build_result.json'),'TEMP':os.environ['TEMP'],'TMP':os.environ['TMP']},
        'production_changes':False,'game_run':False,'quality_accepted':False,
        'limitations':['Frozen synthetic wave sequence; no current-alpha game scheduling or stain cause.','SDK recording discard support and opaque state rollback contract are not established.','Call-presence intervention does not identify an opaque SDK internal mechanism.','Observed native/context repeats are descriptive, not a determinism oracle or universal RESET contract.'],
        'requires_before_any_native':'Root authorization only after independent SolHigh source/preregistration/accounting review. This preparation does not execute a native/GPU job.'}
    save(HERE/'registration.json',registration)
    externals=[base,PRIOR/'execution_completion_manifest.json',PRIOR/'analyze.py',PRIOR/'native_work_accounting_v3.py',ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_rr_runner.cpp',DLL,ROOT/'OptiScaler/shaders/shader_tools/fsrd_toolchain.py']+headers+[p for p in SOURCE.iterdir()if p.is_file()and(p.name in('job.txt','frame_controls.txt','camera.txt','dispatch_controls.bin','amd_context_identity.json')or p.name.startswith('input'))]
    files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
    save(HERE/'pre_native_freeze.json',{'schema':'matched-gap-CPUrecord-before-any-native-freeze-v1','UTC':datetime.now(timezone.utc).isoformat(),'files':[identity(p)for p in files],'external_sources':[identity(p)for p in externals],'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0})
    print(json.dumps({'registration':identity(HERE/'registration.json'),'freeze':identity(HERE/'pre_native_freeze.json'),'source':identity(cpp),'EXE':identity(HERE/'fsrd_rr_gap_control.exe'),'planned':[8,508,504,4,4],'actual_native_contexts':0}),flush=True)
if __name__=='__main__':main()
