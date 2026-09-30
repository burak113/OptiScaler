"""Full isolated Release/x64 solution compile/link; no build events/deployment."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,subprocess,sys
from owned_build_job_guard import run_guarded_build
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha');HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'OptiScaler/shaders/shader_tools'))
import fsrd_toolchain
SOURCE=ROOT/'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,v):
    with Path(p).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def capture(name,args,env):
    r=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,timeout=120,check=False)
    for suffix,data in(('stdout.bin',r.stdout),('stderr.bin',r.stderr)):
        with(HERE/f'{name}.{suffix}').open('xb')as f:f.write(data)
    return{'args':args,'returncode':r.returncode,'stdout':identity(HERE/f'{name}.stdout.bin'),'stderr':identity(HERE/f'{name}.stderr.bin')},r
def production_files():
    paths=[SOURCE,ROOT/'OptiScaler.sln',ROOT/'OptiScaler/OptiScaler.vcxproj',ROOT/'OptiScaler/resource_build_date.h',ROOT/'OptiScaler/resource_build_commit.h',ROOT/'OptiScaler/shaders/shader_tools/fsrd_toolchain.py']
    paths +=[p for p in(ROOT/'OptiScaler/shaders').rglob('*')if p.is_file()and p.suffix.lower()in('.hlsl','.hlsli','.h','.cpp','.cso','.spv')]
    paths +=list((ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin').glob('*.dll'))
    paths +=[ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX'/p for p in('api/include/ffx_api_loader.h','api/include/dx12/ffx_api_dx12.h','api/include/ffx_api.h','api/include/ffx_api_types.h','denoisers/include/ffx_denoiser.h')]
    return sorted(set(paths))
def main():
    assert not(HERE/'build_command.json').exists(),'Preserve prior build attempt'
    assert sha(SOURCE)=='d2cb58c65f6e9d3699e56e34675e6d50593b2bd89bd568025083cb8e09fdd628'
    for name in('tmp','out','obj'):(HERE/name).mkdir(exist_ok=False)
    env=dict(os.environ);env.update(TEMP=str(HERE/'tmp'),TMP=str(HERE/'tmp'),CL_MPCount='1',MSBUILDEMITSOLUTION='0')
    env.pop('CL',None);env.pop('_CL_',None)
    vs=fsrd_toolchain.visual_studio();msbuild=vs/'MSBuild/Current/Bin/amd64/MSBuild.exe'
    if not msbuild.is_file():msbuild=fsrd_toolchain.msbuild()
    props=['/p:Configuration=Release','/p:Platform=x64','/p:PlatformToolset=v143','/p:PreferredToolArchitecture=x64',f'/p:SolutionDir={ROOT.as_posix()}/',
        f'/p:OutDir={(HERE/"out").as_posix()}/',f'/p:IntDir={(HERE/"obj").as_posix()}/',f'/p:ForceImportAfterCppTargets={(HERE/"isolated_build_overrides.targets").as_posix()}',
        '/p:PreBuildEventUseInBuild=false','/p:PostBuildEventUseInBuild=false','/p:UseMultiToolTask=false','/p:BuildInParallel=false','/p:CL_MPCount=1']
    probes={};probes['msbuild_version'],version=capture('MSBuild_version',[str(msbuild),'-version','-nologo'],env);assert version.returncode==0
    evaluate=[str(msbuild),str(ROOT/'OptiScaler/OptiScaler.vcxproj'),'/nologo','/nodeReuse:false']+props+['-getProperty:Configuration,Platform,PlatformToolset,VCToolsInstallDir,VCTargetsPath,WindowsTargetPlatformVersion,OutDir,IntDir,PreBuildEventUseInBuild,PostBuildEventUseInBuild,UseMultiToolTask,CL_MPCount','-getItem:ClCompile,Link']
    probes['evaluation'],evaluated=capture('effective_evaluation',evaluate,env);assert evaluated.returncode==0,evaluated.stderr.decode(errors='replace')
    data=json.loads(evaluated.stdout.decode('utf-8-sig'));properties=data['Properties'];items=data['Items']['ClCompile']
    assert(properties['Configuration'],properties['Platform'],properties['PlatformToolset'])==('Release','x64','v143')
    assert properties['PreBuildEventUseInBuild']==properties['PostBuildEventUseInBuild']==properties['UseMultiToolTask']=='false'and properties['CL_MPCount']=='1'
    assert all(i['MultiProcessorCompilation']=='false'for i in items)
    source_item=next(i for i in items if Path(i['FullPath'])==SOURCE)
    compiler=Path(properties['VCToolsInstallDir'])/'bin/Hostx64/x64/cl.exe';linker=compiler.parent/'link.exe';assert compiler.is_file()and linker.is_file()
    probes['compiler_version'],_=capture('compiler_version',[str(compiler),'/Bv'],env)
    probes['linker_help'],linkhelp=capture('linker_help',[str(linker),'/?'],env);assert b'CGTHREADS'in(linkhelp.stdout+linkhelp.stderr).upper()
    save(HERE/'tool_and_effective_settings.json',{'schema':'Release-isolated-effective-settings-v1','visual_studio_root':str(vs),'msbuild':identity(msbuild),'compiler':identity(compiler),'linker':identity(linker),
        'probes':probes,'properties':properties,'ClCompile_items':len(items),'all_compile_items_MP_false':True,'changed_source_compile_item':source_item,
        'late_override':identity(HERE/'isolated_build_overrides.targets'),'pre_and_post_build_events_skipped':True,'link_LTCG_threads':1})
    head=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD']).decode().strip();status=subprocess.check_output(['git','-C',str(ROOT),'status','--short'])
    diff=subprocess.check_output(['git','-C',str(ROOT),'diff','--','OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'])
    base=subprocess.check_output(['git','-C',str(ROOT),'show','HEAD:OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'])
    for name,raw in(('source_current_build.cpp',SOURCE.read_bytes()),('source_committed_base_git_blob.cpp',base),('dirty_source.diff',diff),('git_status_before.bin',status)):
        with(HERE/name).open('xb')as f:f.write(raw)
    numstat=subprocess.check_output(['git','-C',str(ROOT),'diff','--numstat','--','OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp']).decode().strip();assert numstat.startswith('8\t0\t'),numstat
    paths=production_files();before=[identity(p)for p in paths]
    save(HERE/'production_before.json',{'schema':'before-full-Release-compile-provider-shader-byte-snapshot-v1','UTC':datetime.now(timezone.utc).isoformat(),'head':head,'dirty_source_numstat':numstat,
        'dirty_source':identity(SOURCE),'committed_base_git_blob':identity(HERE/'source_committed_base_git_blob.cpp'),'base_line_ending_qualification':'Git committed blob may use LF; original18prechange working-source snapshots remain separately archived by root.',
        'files':before,'provider_DLL':identity(ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll')})
    command=[str(msbuild),str(ROOT/'OptiScaler.sln'),'/t:Build','/m:1','/nodeReuse:false','/nologo','/v:normal']+props+[f'/bl:{(HERE/"full_build.binlog").as_posix()}',f'/flp:LogFile={(HERE/"full_build.log").as_posix()};Verbosity=normal;Encoding=UTF-8']
    save(HERE/'build_command.json',{'schema':'full-solution-Release-x64-build-command-v1','args':command,'cwd':str(ROOT),'environment_overrides':{k:env[k]for k in('TEMP','TMP','CL_MPCount','MSBUILDEMITSOLUTION')},
        'removed_process_only_options':['CL','_CL_'],'head':head,'source_sha256':sha(SOURCE),'solution':identity(ROOT/'OptiScaler.sln'),'project':identity(ROOT/'OptiScaler/OptiScaler.vcxproj'),
        'scope':'Full solution single-project Release compile/link. Prebuild resource header regeneration and postbuild packaging disabled to preserve production bytes/no deployment. No shader tests, nativeSDK fixture, GPU or game execution.'})
    print(json.dumps({'status':'starting_owned_full_Release_build','compile_items':len(items),'source_sha256':sha(SOURCE),'head':head,'command':str(HERE/'build_command.json')}),flush=True)
    guard=run_guarded_build(command,HERE,ROOT,env)
    after=[identity(p)for p in paths];unchanged=before==after
    with(HERE/'git_status_after.bin').open('xb')as f:f.write(subprocess.check_output(['git','-C',str(ROOT),'status','--short']))
    with(HERE/'dirty_source_after.diff').open('xb')as f:f.write(subprocess.check_output(['git','-C',str(ROOT),'diff','--','OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp']))
    save(HERE/'production_after.json',{'schema':'after-full-Release-provider-shader-byte-snapshot-v1','head':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD']).decode().strip(),'files':after,'all_before_after_byte_identities_exact':unchanged})
    dll=HERE/'out/OptiScaler.dll';text=(HERE/'build.stdout.bin').read_text(errors='replace');warning_lines=[s for s in text.splitlines()if re.search(r'\bwarning [A-Z]+\d+\b',s,re.I)];error_lines=[s for s in text.splitlines()if re.search(r'\berror [A-Z]+\d+\b',s,re.I)]
    result={'schema':'full-solution-isolated-Release-x64-build-result-v1','status':'compile_link_completed'if guard['status']=='completed'and dll.is_file()and unchanged else'failed_preserved',
        'returncode':guard['returncode'],'guard':guard,'source_sha256':sha(SOURCE),'source_and_shaders_providers_project_resource_headers_unchanged':unchanged,
        'output_DLL':identity(dll)if dll.is_file()else None,'changed_source_obj':identity(HERE/'obj/FSRDFeature_Dx12.obj')if(HERE/'obj/FSRDFeature_Dx12.obj').is_file()else None,
        'warnings_log_lines_including_MSBuild_summary_duplicates':warning_lines,'unique_warning_lines':sorted(set(warning_lines)),'error_lines':error_lines,
        'postbuild_packaging_status':'intentionally_not_run_via_PostBuildEventUseInBuild=false; no archive, copy, move, deploy or game-folder output',
        'prebuild_metadata_status':'intentionally_not_run; existing production resource_build_date/commit headers retained byte-exact; release version timestamp is existing metadata',
        'nativeSDK_dispatches':0,'GPU_jobs':0,'game_runs':0,'deployment':False,'quality_accepted':False,
        'validation_scope':'Full Release/x64 solution compilation and link only; no claim of runtime game quality or stain cause.'}
    save(HERE/'build_result.json',result)
    print(json.dumps({'status':result['status'],'returncode':guard['returncode'],'DLL':result['output_DLL'],'unchanged':unchanged,'unique_warning_lines':len(set(warning_lines))}),flush=True)
if __name__=='__main__':main()
