import json,os
from pathlib import Path
keys=("PATH","INCLUDE","LIB","LIBPATH","VCToolsInstallDir","WindowsSdkDir","WindowsSDKVersion","UniversalCRTSdkDir","UCRTVersion")
with(Path(__file__).parent/"compile_environment.json").open("x",encoding="utf-8")as f:json.dump({k:os.environ.get(k,"")for k in keys},f,indent=2)
