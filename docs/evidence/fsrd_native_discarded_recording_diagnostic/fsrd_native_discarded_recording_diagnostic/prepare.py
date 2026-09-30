"""Prepare/build/preregister discarded-record H2. This script launches no GPU/native runner."""
from pathlib import Path
from datetime import datetime,timezone
import difflib,hashlib,json,os,shlex,shutil,struct,subprocess,sys
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha');HERE=Path(__file__).resolve().parent
ORIGINAL=ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_rr_runner.cpp'
SOURCE=ROOT/'tools_tmp/native_continuous_harmonic_remaining_20260930/evidence/wave/harmonic_pilot'
DLL=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
ORDER=[f'round0_{s}'for s in('baseline','discard24','discard24_reset25','fresh_tail25')]+[f'round1_{s}'for s in('fresh_tail25','discard24_reset25','discard24','baseline')]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,v):
    with Path(p).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def write(p,t):
    with Path(p).open('x',encoding='utf-8',newline='\n')as f:f.write(t)
def main():
    if(HERE/'registration.json').exists()or(HERE/'fsrd_rr_discard.cpp').exists():raise ValueError('Preserve preparation')
    assert sha(ORIGINAL)=='f6cfbecc4704d7f4f891f5c2ae88baf69546a316a9738ed03da0413d6ef0d077'
    assert sha(DLL)=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
    text=ORIGINAL.read_text();changes=[]
    for token in('api/include/ffx_api_loader.h','api/include/dx12/ffx_api_dx12.h','denoisers/include/ffx_denoiser.h'):
        before='../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/'+token;after=(ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX'/token).as_posix()
        assert text.count(before)==1;text=text.replace(before,after);changes.append({'kind':'absolute_include','before':before,'after':after})
    def replace(before,after,label):
        nonlocal text
        assert text.count(before)==1,label;text=text.replace(before,after);changes.append({'kind':'source_replacement','label':label,'before':before,'after':after})
    replace('if(argc!=2) throw std::runtime_error("usage: fsrd_rr_runner job.txt");',
'''if(argc<2||argc>5) throw std::runtime_error("usage: fsrd_rr_discard job.txt [skip_frame=-1] [recovery_reset_frame=-1] [source_frame_start=0]");
    const int skipFrame=argc>=3?std::stoi(argv[2]):-1;
    const int recoveryResetFrame=argc>=4?std::stoi(argv[3]):-1;
    const unsigned sourceFrameStart=argc>=5?unsigned(std::stoul(argv[4])):0;
    if(skipFrame < -1 || recoveryResetFrame < -1 || sourceFrameStart>63) throw std::runtime_error("invalid diagnostic frame arguments");
    std::cout<<"skip_frame="<<skipFrame<<" recovery_reset_frame="<<recoveryResetFrame<<" source_frame_start="<<sourceFrameStart<<'\\n';''','optional_frame_arguments')
    replace('    if(!job||!w||!h||!frames) throw std::runtime_error("invalid header");',
'''    if(!job||!w||!h||!frames) throw std::runtime_error("invalid header");
    if(sourceFrameStart+frames>64 || (skipFrame>=0 && (unsigned(skipFrame)<sourceFrameStart || unsigned(skipFrame)>=sourceFrameStart+frames)) ||
       (recoveryResetFrame>=0 && (unsigned(recoveryResetFrame)<sourceFrameStart || unsigned(recoveryResetFrame)>=sourceFrameStart+frames)))
        throw std::runtime_error("diagnostic source frame outside job");''','source_frame_range')
    replace('    std::vector<char> row(size_t(w)*8);',
'''    std::ofstream presenceOut(std::filesystem::path(argv[1]).parent_path()/"output_presence.bin",std::ios::binary);
    std::ofstream frameIndicesOut(std::filesystem::path(argv[1]).parent_path()/"observed_frame_indices.bin",std::ios::binary);
    std::ofstream recordedFrameIndicesOut(std::filesystem::path(argv[1]).parent_path()/"recorded_frame_indices.bin",std::ios::binary);
    if(!presenceOut||!frameIndicesOut||!recordedFrameIndicesOut) throw std::runtime_error("presence/index output open");
    unsigned successfulRecordings=0,queuedDispatches=0,discardedRecordings=0;
    int previousSubmittedSourceFrame=-1; UINT64 previousCompletedFence=0;
    std::vector<char> row(size_t(w)*8);''','presence_and_recording_counters')
    replace('        hr(alloc->Reset(),"reset allocator"); hr(cmd->Reset(alloc.Get(),nullptr),"reset list");',
'''        hr(alloc->Reset(),"reset allocator"); hr(cmd->Reset(alloc.Get(),nullptr),"reset list");
        const unsigned sourceFrame=sourceFrameStart+frame;
        std::array<D3D12_RESOURCE_STATES,9> externalStatesBeforeRecording{};
        for(unsigned i=0;i<9;++i) externalStatesBeforeRecording[i]=tex[i].state;''','external_state_snapshot')
    replace('        dispatch.frameIndex=frame;','        dispatch.frameIndex=sourceFrame;','source_frame_index')
    replace('        auto record=[&](const auto& value) { controlsOut.write(reinterpret_cast<const char*>(&value),sizeof(value)); };',
'''        if(recoveryResetFrame>=0 && sourceFrame==unsigned(recoveryResetFrame)) dispatch.flags|=FFX_DENOISER_DISPATCH_RESET;
        auto record=[&](const auto& value) { controlsOut.write(reinterpret_cast<const char*>(&value),sizeof(value)); };''','recovery_reset_only_at_registered_source_frame')
    replace('        ff(api.Dispatch(&context,&dispatch.header),"dispatch RR");',
'''        ff(api.Dispatch(&context,&dispatch.header),"dispatch RR");
        ++successfulRecordings;
        recordedFrameIndicesOut.write(reinterpret_cast<const char*>(&sourceFrame),sizeof(sourceFrame));
        if(skipFrame>=0 && sourceFrame==unsigned(skipFrame)) {
            // A successful SDK recording is deliberately abandoned. No output
            // copy, queue Execute, Signal, fence wait, or readback for this frame.
            // Prior submitted frame completed in the original loop below.
            if(previousSubmittedSourceFrame!=int(sourceFrame)-1 || previousCompletedFence==0)
                throw std::runtime_error("discard requires completed immediately prior submission");
            hr(cmd->Close(),"close discarded recording");
            for(unsigned i=0;i<9;++i) tex[i].state=externalStatesBeforeRecording[i];
            const char absent=0; presenceOut.write(&absent,1); ++discardedRecordings;
            std::cout<<"discarded_recording source_frame="<<sourceFrame<<" previous_submitted_source_frame="<<previousSubmittedSourceFrame
                     <<" previous_completed_fence="<<previousCompletedFence<<" external_state_shadow_restored=1 queued=0 observed_output=0\\n";
            continue;
        }''','successful_API_record_then_discard_without_submission')
    replace('        hr(dev->GetDeviceRemovedReason(),"device removed");',
'''        hr(dev->GetDeviceRemovedReason(),"device removed");
        ++queuedDispatches; previousSubmittedSourceFrame=int(sourceFrame); previousCompletedFence=frame+1;''','executed_dispatch_accounting_after_completed_fence')
    replace('        if(info) {',
'''        const char present=1; presenceOut.write(&present,1);
        frameIndicesOut.write(reinterpret_cast<const char*>(&sourceFrame),sizeof(sourceFrame));
        if(info) {''','presence_and_observed_source_frame_mapping_after_actual_readback')
    replace('    controlsOut.close(); if(!controlsOut) throw std::runtime_error("controls output write");',
'''    controlsOut.close(); if(!controlsOut) throw std::runtime_error("controls output write");
    presenceOut.close(); frameIndicesOut.close(); recordedFrameIndicesOut.close();
    if(!presenceOut||!frameIndicesOut||!recordedFrameIndicesOut) throw std::runtime_error("presence/index output write");''','close_presence_outputs')
    replace('    std::cout<<"dispatches="<<frames<<" validation_errors="<<validationErrors<<" validation_warnings="<<validationWarnings<<" sdk_errors="<<sdkErrors<<" sdk_warnings="<<sdkWarnings<<\'\\n\';',
'''    std::cout<<"RR_recordings="<<successfulRecordings<<" queued_RR_dispatches="<<queuedDispatches<<" discarded_RR_recordings="<<discardedRecordings
             <<" validation_errors="<<validationErrors<<" validation_warnings="<<validationWarnings<<" sdk_errors="<<sdkErrors<<" sdk_warnings="<<sdkWarnings<<'\\n';''','separate_recorded_queued_discarded_completion_counts')
    # The sole additional standard include is needed for the nine-state snapshot.
    replace('#include <vector>','#include <vector>\n#include <array>','standard_array_include')
    cpp=HERE/'fsrd_rr_discard.cpp';write(cpp,text)
    shutil.copyfile(ORIGINAL,HERE/'original_fsrd_rr_runner.cpp')
    save(HERE/'source_insertion_whitelist.json',{'original':identity(ORIGINAL),'new_source':identity(cpp),'operations':changes})
    write(HERE/'source_insertion_whitelist.diff',''.join(difflib.unified_diff(ORIGINAL.read_text().splitlines(keepends=True),text.splitlines(keepends=True),fromfile='original_fsrd_rr_runner',tofile='isolated_discard_runner')))
    guard=ROOT/'tools_tmp/native_output_initialization_diagnostic_20260930/native_resource_guard.py'
    assert sha(guard)=='b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814';shutil.copyfile(guard,HERE/'native_resource_guard.py')
    os.environ['TEMP']=str(ROOT/'tools_tmp/native_compile_temp_20260930');os.environ['TMP']=os.environ['TEMP'];assert Path(os.environ['TEMP']).is_dir()
    args=[sys.executable,str(HERE/'build_runner.py')]
    save(HERE/'build_command.json',{'args':args,'TEMP':os.environ['TEMP'],'TMP':os.environ['TMP']})
    built=subprocess.run(args,cwd=HERE,capture_output=True);(HERE/'build.stdout.bin').write_bytes(built.stdout);(HERE/'build.stderr.bin').write_bytes(built.stderr)
    assert built.returncode==0,'Preserve failed build bytes; no native work ran'
    jobrows=[shlex.split(row)for row in(SOURCE/'job.txt').read_text().splitlines()]
    assert len(jobrows)==9 and list(map(int,jobrows[0][:8]))==[128,80,64,2,32,0,1,0]
    assert Path(jobrows[0][8])==DLL
    assert[int(r[1])for r in jobrows[1:8]]==[41,10,24,28,28,10,10]
    assert[int(r[2])for r in jobrows[1:8]]==[1,1,1,1,1,64,64]
    source_controls=(SOURCE/'dispatch_controls.bin').read_bytes();assert len(source_controls)==64*184
    source_identity=json.loads((SOURCE/'amd_context_identity.json').read_text())
    assert source_identity['inputs']=={f'input{i}.bin':sha(SOURCE/f'input{i}.bin')for i in range(7)}
    assert source_identity['applied_dispatch_sha256']==sha(SOURCE/'dispatch_controls.bin')
    assert source_identity['dll_sha256']==sha(DLL)
    for i,row in enumerate(jobrows[1:8]):assert Path(row[0])==SOURCE/f'input{i}.bin'
    for frame in range(64):
        assert struct.unpack_from('<4I',source_controls,frame*184)==(frame,3 if frame==0 else 2,128,80)
    source_control_lines=(SOURCE/'frame_controls.txt').read_text().splitlines();assert len(source_control_lines)==64
    cases=[]
    for tag in ORDER:
        kind=tag.split('_',1)[1];tail=kind=='fresh_tail25';count=39 if tail else 64;base=25 if tail else 0
        skip=24 if kind in('discard24','discard24_reset25')else-1;reset=25 if kind=='discard24_reset25'else-1
        folder=HERE/'evidence'/tag;folder.mkdir(parents=True,exist_ok=False);input_records=[];lines=[]
        for i,row in enumerate(jobrows[1:8]):
            src=Path(row[0]);fmt,uploads=map(int,row[1:]);data=src.read_bytes();bpp=8 if fmt==10 else 4
            assert len(data)==128*80*bpp*uploads
            data=data[25*128*80*bpp:]if tail and uploads==64 else data
            new_uploads=39 if tail and uploads==64 else uploads
            dest=folder/f'input{i}.bin';dest.write_bytes(data)
            assert len(data)==128*80*bpp*new_uploads
            input_records.append({**identity(dest),'index':i,'DXGI_format':fmt,'uploads':new_uploads,'source':identity(src),
                                  'source_frame_start':25 if tail and uploads==64 else 0,'source_frame_count':new_uploads})
            lines.append(f'"{dest.as_posix()}" {fmt} {new_uploads}')
        frame_text='\n'.join(source_control_lines[25:]if tail else source_control_lines)+'\n';write(folder/'frame_controls.txt',frame_text)
        if(SOURCE/'camera.txt').exists():shutil.copyfile(SOURCE/'camera.txt',folder/'camera.txt')
        control=bytearray(source_controls[25*184:]if tail else source_controls)
        if tail:struct.pack_into('<I',control,4,struct.unpack_from('<I',control,4)[0]|1)
        if reset>=0:struct.pack_into('<I',control,(reset-base)*184+4,struct.unpack_from('<I',control,(reset-base)*184+4)[0]|1)
        (folder/'expected_applied_dispatch_controls.bin').write_bytes(control)
        expected_presence=bytes(0 if base+i==skip else 1 for i in range(count));(folder/'expected_output_presence.bin').write_bytes(expected_presence)
        indices=[base+i for i,b in enumerate(expected_presence)if b];(folder/'expected_observed_frame_indices.bin').write_bytes(struct.pack('<'+str(len(indices))+'I',*indices))
        header=[128,80,count,2,32,0,1,0]
        write(folder/'job.txt',' '.join(map(str,header))+f' "{DLL.as_posix()}"\n'+'\n'.join(lines)+f'\n"{(folder/"diffuse.bin").as_posix()}" "{(folder/"specular.bin").as_posix()}"\n')
        case={'tag':tag,'kind':kind,'frames_recorded':count,'frames_queued':len(indices),'frames_discarded':count-len(indices),
              'skip_frame':skip,'recovery_reset_frame':reset,'source_frame_start':base,'source_frame_indices':list(range(base,base+count)),
              'observed_frame_indices':indices,'output_presence_mask':list(expected_presence),
              'command':[str(HERE/'fsrd_rr_discard.exe'),str(folder/'job.txt'),str(skip),str(reset),str(base)],
              'inputs':input_records,'expected_applied_dispatch_controls':identity(folder/'expected_applied_dispatch_controls.bin'),
              'expected_output_presence':identity(folder/'expected_output_presence.bin'),'expected_observed_frame_indices':identity(folder/'expected_observed_frame_indices.bin'),
              'expected_raw_lobe_bytes':len(indices)*128*80*8,'job':identity(folder/'job.txt'),'frame_controls':identity(folder/'frame_controls.txt')}
        cases.append(case)
    assert sum(c['frames_recorded']for c in cases)==462 and sum(c['frames_queued']for c in cases)==458 and sum(c['frames_discarded']for c in cases)==4
    registration={'schema':'native-successful-recording-discard-H2-preparation-v1','utc':datetime.now(timezone.utc).isoformat(),
        'branch':subprocess.check_output(['git','-C',str(ROOT),'branch','--show-current']).decode().strip(),
        'head':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD']).decode().strip(),
        'status':'prepared_built_preregistered_NOT_AUTHORIZED_TO_RUN','preparation_only':True,
        'hypothesis':'After api.Dispatch successfully records frame24, discarding without queue execution may change later SDK context output through CPU/internal history advancement. The test investigates a conditional H2 effect; it does not establish supported SDK rollback semantics.',
        'mode_order':ORDER,'cases':cases,'planned_native_contexts':8,'planned_successful_API_RR_recordings':462,
        'planned_discarded_API_RR_recordings':4,'planned_queued_RR_dispatches':458,
        'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0,
        'original_runner':identity(ORIGINAL),'new_source':identity(cpp),'new_binary':identity(HERE/'fsrd_rr_discard.exe'),'dll':identity(DLL),
        'source_frozen_wave_P':str(SOURCE),'source_controls':identity(SOURCE/'dispatch_controls.bin'),'source_previous_context_identity':identity(SOURCE/'amd_context_identity.json'),
        'settings':{'dimensions':[128,80],'diffuse_signal':2,'specular_signal':32,'reset_every':0,'tuning':1,'passthrough':0,
                    'tuning_values':[.1,.5,.5,40000.,40.,.5],'provider_requested_API':4202496,'formats':[41,10,24,28,28,10,10]},
        'discard_lifecycle':'Record uploads and successful api.Dispatch, close abandoned list, restore external Tex.state CPU shadow to pre-record snapshot, mark output24 absent, continue. Next loop Reset occurs after prior submitted frame23 fence completed. No frame24 Execute/Signal/copy/readback. SDK opaque CPU state is deliberately not rolled back.',
        'tail_control_matching':'Fresh context records original source frameIndex25..63 (39), static guides1 and radiance raw tail39, exact original tail frame-control lines. First sourceframe25 RESET is expected. Its 184-byte records match discard24_reset25 corresponding tail exactly; fresh context/configuration history still differs, so output-bit identity is not assumed.',
        'controls_matching':'Baseline/discard24 applied API controls exact original64; reset arm differs solely RESET bit at sourceframe25; frame24 controls retained although not submitted. Output masks/indices disambiguate recorded versus queued versus observed.',
        'analysis_plan':{'all_pair_context_combinations':28,'lobes':['diffuse.bin','specular.bin'],
            'channel_metrics':['raw RGB uint16 bit equality','RGB/RGBA/alpha float64 RMS','maximum absolute difference','changed component fraction','per-frame metrics'],
            'alignment':['Submitted ordinal comparison explicitly records each side sourceframe and 184-byte applied-control/flag identity; ordinal-after-drop sourceframe shift is not concealed.',
                         'Common observed logical sourceframe intersection comparison annotates flag/control match; frame24 never enters discarded observed metrics.',
                         'Recovery25 tail versus fresh-tail25 compares source25..63 with exact registered flags/controls; baseline/drop tail firstflag differences stay visible.'],
            'interpretation':'No quality/truth/oracle thresholds, averaging-away variation, or expected exact native determinism. Compare repeats descriptively and preserve every raw output. No missing output replacement by fabricated zeros.'},
        'guard':{'source_sha256':sha(HERE/'native_resource_guard.py'),'timeout_seconds':240,'maximum_working_set_bytes':2*1024**3,'minimum_available_memory_bytes':1024**3,'sample_interval_seconds':.2,
                 'policy':'Refuse launch below free1GiB; sequential owned child only; terminate only that owned child if guard requires; never kill other processes.'},
        'build':{'command':identity(HERE/'build_command.json'),'MSVC_command':identity(HERE/'fsrd_rr_discard.build.cmd'),'stdout':identity(HERE/'build.stdout.bin'),'stderr':identity(HERE/'build.stderr.bin'),
                 'TEMP':os.environ['TEMP'],'TMP':os.environ['TMP']},
        'production_changes':False,'game_run':False,'quality_accepted':False,
        'limitations':['A synthetic frozen wave input, no current-alpha game scheduling/capture or stain cause.',
                       'Discarded SDK recording may be unsupported; no header/runtime rollback guarantee is asserted.',
                       'External resource state shadow restoration does not restore opaque SDK internal CPU state.',
                       'Native context variation and fresh-context history remain separate; reset comparison is not a determinism oracle.'],
        'requires_before_any_native':'Root authorization after independent source/preregistration reviews; preparation alone does not authorize execution.'}
    save(HERE/'registration.json',registration)
    sources=[ORIGINAL,DLL,ROOT/'OptiScaler/shaders/shader_tools/fsrd_toolchain.py']+[p for p in SOURCE.iterdir()if p.is_file()and(p.name in('job.txt','frame_controls.txt','camera.txt','dispatch_controls.bin','amd_context_identity.json')or p.name.startswith('input'))]
    files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
    save(HERE/'pre_native_freeze.json',{'schema':'discarded-recording-H2-before-any-native-byte-freeze-v1','utc':datetime.now(timezone.utc).isoformat(),
        'files':[identity(p)for p in files],'external_sources':[identity(p)for p in sources],
        'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0})
    print(json.dumps({'status':registration['status'],'registration':identity(HERE/'registration.json'),'freeze':identity(HERE/'pre_native_freeze.json'),
                      'planned_contexts':8,'planned_RR_recordings':462,'planned_discarded':4,'planned_queued':458,'actual_native_contexts':0}),flush=True)
if __name__=='__main__':main()
