import os
import subprocess
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
root=Path(__file__).resolve().parents[2]
work=Path('F:/FSRD/sol_batch/21-input-parity')
os.environ['TEMP']=os.environ['TMP']='F:/FSRD/tmp'
args=['F:/VisualStudio/MSBuild/Current/Bin/MSBuild.exe',str(root/'OptiScaler.sln'),
      '/t:Build','/p:Configuration=Release','/p:Platform=x64',
      '/p:OutDir=F:\\FSRD\\sol_batch\\21-input-parity\\build\\out\\',
      '/p:IntDir=F:\\FSRD\\sol_batch\\21-input-parity\\build\\obj\\',
      '/p:PostBuildEventUseInBuild=false','/p:CL_MPCount=2','/m:2','/v:minimal']
work.mkdir(parents=True,exist_ok=True)
with open(work/'build.log','w',encoding='utf-8') as log:
    p=subprocess.run(args,cwd=root,stdout=log,stderr=subprocess.STDOUT,
                     creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS|subprocess.CREATE_NO_WINDOW)
print('BUILD_EXIT',p.returncode,flush=True)
if p.returncode:
    print((work/'build.log').read_text(encoding='utf-8',errors='replace')[-14000:])
sys.exit(p.returncode)
