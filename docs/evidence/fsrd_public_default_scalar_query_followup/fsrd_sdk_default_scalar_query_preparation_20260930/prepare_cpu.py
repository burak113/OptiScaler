"""Own query preparation, then one guarded CPU compiler. Never invokes query EXE."""
from pathlib import Path
import ast,hashlib,json,os,shutil,subprocess,sys
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent
def rec(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def write(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:f.write(v)
assert not(HERE/'pre_compile_freeze.json').exists(),'Preserve prior prep; no automatic retry'
design=ROOT/'tools_tmp/fsrd_sdk_default_scalar_query_design_20260930'
assert rec(design/'design.json')['sha256']=='bb80daa56058ef57f7be03d37ef217acaaca8f4ad285b5bee4cad1ddf3f372e6'
old=ROOT/'tools_tmp/fsrd_clean_specular_hit_alpha_contrast_preparation_20260930'
for n in('native_resource_guard.py','executor_evidence.py'):
 assert not(HERE/n).exists();shutil.copyfile(old/n,HERE/n);assert(HERE/n).read_bytes()==(old/n).read_bytes()
assert rec(HERE/'native_resource_guard.py')['sha256']=='b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814'
provider=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
assert rec(provider)['sha256']=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
for n in('planned_query','execution_TEMP','compile_TEMP','compile_runtime'):(HERE/n).mkdir(exist_ok=False)
job=HERE/'planned_query/job.txt';job.write_text('"'+provider.as_posix()+'"\n',encoding='utf-8',newline='\n')
write('capture_compile_env.py','import json,os\nfrom pathlib import Path\nkeys=("PATH","INCLUDE","LIB","LIBPATH","VCToolsInstallDir","WindowsSdkDir","WindowsSDKVersion","UniversalCRTSdkDir","UCRTVersion")\nwith(Path(__file__).parent/"compile_environment.json").open("x",encoding="utf-8")as f:json.dump({k:os.environ.get(k,"")for k in keys},f,indent=2)\n')
sys.path.insert(0,str(ROOT/'OptiScaler/shaders/shader_tools'));from fsrd_toolchain import visual_studio
vs=visual_studio();vcvars=vs/'VC/Auxiliary/Build/vcvars64.bat';versionfile=vs/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt';version=versionfile.read_text().strip();compiler=vs/'VC/Tools/MSVC'/version/'bin/Hostx64/x64/cl.exe';linker=compiler.parent/'link.exe'
write('capture_compile_env.cmd',f'@call "{vcvars}" >nul\n@if errorlevel 1 exit /b %errorlevel%\n@"{sys.executable}" -B "{HERE/"capture_compile_env.py"}"\n')
environment=dict(os.environ,TEMP=str(HERE/'compile_TEMP'),TMP=str(HERE/'compile_TEMP'))
envproc=subprocess.run(['cmd.exe','/d','/s','/c',str(HERE/'capture_compile_env.cmd')],cwd=HERE,env=environment,capture_output=True)
(HERE/'environment_setup.stdout.bin').write_bytes(envproc.stdout);(HERE/'environment_setup.stderr.bin').write_bytes(envproc.stderr)
save('environment_setup_result.json',dict(returncode=envproc.returncode,stdout=rec(HERE/'environment_setup.stdout.bin'),stderr=rec(HERE/'environment_setup.stderr.bin'),CPU_toolchain_setup_only=True,no_query_EXE_invoked=True))
assert envproc.returncode==0,'Preserve environment failure'
selected=json.loads((HERE/'compile_environment.json').read_text());os.environ.update(selected);os.environ['TEMP']=str(HERE/'compile_TEMP');os.environ['TMP']=str(HERE/'compile_TEMP')
sdk=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX'
command=[str(compiler),'/nologo','/std:c++20','/EHsc','/O2','/I'+str(sdk/'api/include'),'/I'+str(sdk/'denoisers/include'),str(HERE/'fsrd_default_query.cpp'),'/Fe:'+str(HERE/'fsrd_default_query.exe'),'/Fo:'+str(HERE/'fsrd_default_query.obj'),'/link','d3d12.lib','dxgi.lib']
write('actual_compiler_command.txt','\n'.join(command)+'\n')
external=[rec(p)for p in(design/'design.json',design/'completion_manifest.json',old/'native_resource_guard.py',old/'executor_evidence.py',provider,ROOT/'OptiScaler/shaders/shader_tools/fsrd_toolchain.py',vcvars,versionfile,compiler,linker,sdk/'api/include/ffx_api.h',sdk/'api/include/ffx_api_types.h',sdk/'api/include/ffx_api_loader.h',sdk/'api/include/dx12/ffx_api_dx12.h',sdk/'denoisers/include/ffx_denoiser.h')]
for p in HERE.glob('*.py'):ast.parse(p.read_text())
check=subprocess.run([sys.executable,'-B',str(HERE/'check_query_cpu.py')],cwd=HERE,capture_output=True)
(HERE/'CPU_checks.stdout.bin').write_bytes(check.stdout);(HERE/'CPU_checks.stderr.bin').write_bytes(check.stderr)
save('CPU_checks_result.json',dict(returncode=check.returncode,stdout=rec(HERE/'CPU_checks.stdout.bin'),stderr=rec(HERE/'CPU_checks.stderr.bin'),actual_query_native_GPU=0));assert check.returncode==0,'Preserve CPU check failures'
save('pre_compile_freeze.json',dict(owned=[rec(p)for p in sorted(HERE.rglob('*'))if p.is_file()],external_sources=external,self_entry_excluded=True,command=command,planned_compiler_invocations=1,actual_query_native_GPU=0))
save('compile_attempt.json',dict(command=command,actual_started_compile_invocations=1,guard_child_is_direct_cl_exe=True,TEMP=os.environ['TEMP'],TMP=os.environ['TMP'],pre_compile_freeze=rec(HERE/'pre_compile_freeze.json'),query_EXE_invoked=False))
from native_resource_guard import run_guarded
os.chdir(HERE)
guard=None;error=None
try:guard=run_guarded(command,HERE/'compile_runtime',timeout=240,maximum_working_set=2147483648,minimum_available_memory=1073741824,interval=.2)
except BaseException as e:error=type(e).__name__+': '+str(e)
result=dict(guard=guard,error=error,compiler_stdout=rec(HERE/'compile_runtime/stdout.log')if(HERE/'compile_runtime/stdout.log').exists()else None,compiler_stderr=rec(HERE/'compile_runtime/stderr.log')if(HERE/'compile_runtime/stderr.log').exists()else None,actual_compile_invocations=1,query_EXE_invocations=0,actual_query_native_GPU=0)
for n in('fsrd_default_query.exe','fsrd_default_query.obj'):
 if(HERE/n).exists():result[n]=rec(HERE/n)
result['passed']=error is None and isinstance(guard,dict)and guard.get('status')=='completed'and guard.get('returncode')==0 and(HERE/'fsrd_default_query.exe').is_file()
save('build_result.json',result)
for r in external:assert rec(r['path'])==r,r['path']
print(json.dumps(result))
if not result['passed']:raise RuntimeError('CPU compile failure preserved; no retry/query')
