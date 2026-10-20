import sys, os, json, subprocess, hashlib, types
from pathlib import Path
sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding="utf-8",errors="replace")
import argparse
parser=argparse.ArgumentParser()
parser.add_argument("--shader-dir",type=Path)
parser.add_argument("--tag",default="fixed")
parser.add_argument("--expect",choices=["fixed","old","diagnostic"],default="fixed")
args=parser.parse_args()
TAG=args.tag
import numpy as np
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
TESTS = HERE
OUTPUT = Path(os.environ["FSRD_GPU_TEST_OUTPUT"])
OUTPUT.mkdir(parents=True,exist_ok=True)
SH=args.shader_dir or ROOT/"OptiScaler/shaders/fsrd_preprocess/precompile"
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parent))
from fsrd_gpu_chain import ChainJob
import run_fsrd_gpu_tests as runner
runner.build_runner()
RUNNER=runner.runner
result={"baseline_reference":"a79473353d7bc93920f881dbe88f5dfbcf761d1f",
"runner":str(RUNNER),"runner_sha256":hashlib.sha256(RUNNER.read_bytes()).hexdigest(),
"cso":{n:hashlib.sha256((SH/(n+"_Shader.cso")).read_bytes()).hexdigest() for n in ["FSRDPostFlickApply","FSRDPostFlickPrepare","FSRDNrdFlatSelectApply"]}}
def rgba(w,h,v,alpha=1): 
    a=np.full((h,w,4),v,np.float16); a[...,3]=alpha; return a
def apply_case(name,w=64,h=32,shift=0,hist=1,depth=10,strength=1):
    job=ChainJob(OUTPUT/("gpu_"+TAG)/name,runner); hw=max(w//2,1); hh=max(h//2,1)
    color=job.texture("color",rgba(w,h,.2)); aux=np.zeros((hh,hw,2),np.float16); aux[...,1]=10
    job.texture("aux",aux,format=34); job.texture("cur",rgba(hw,hh,.2,alpha=.2))
    job.texture("key",rgba(hw,hh,.4,alpha=.2)); ka=np.zeros((hh,hw,2),np.float16); ka[...,0]=depth; ka[...,1]=1
    job.texture("key_aux",ka,format=34); job.texture("out",size=(w,h),writable=True,readback=True)
    cb=np.zeros(36,np.float32); cb[:4]=[w,h,1/w,1/h]
    mat=np.array([[1,0,0,shift],[0,1,0,0],[0,0,1,0],[0,0,1,0]],np.float32)
    cb[4:20]=mat.ravel(); cb[20:24]=[1,1,0,0]; cb[24:30]=[1,1,.01,32,.7,1.4]
    cb.view(np.uint32)[32]=hist; cb[33:35]=[strength,.25]
    job.compute(name,SH/"FSRDPostFlickApply_Shader.cso",cb.tobytes(),["color","aux","cur","key","key_aux"],["out"],groups=((w+7)//8,(h+7)//8,1))
    out,meta=job.run(keep_staging=False); a=out["out"][...,0].astype(np.float32); base=float(np.float16(.2))
    return dict(min=float(a.min()),max=float(a.max()),changed=int(np.count_nonzero(a!=base)),pixels=w*h,
                interior=float(a[h//2,w//2]),last_col=list(map(float,np.unique(a[:,-1]))),last_row=list(map(float,np.unique(a[-1]))))
def prepare_case(name,mvx):
    w,h=64,32; hw,hh=w//2,h//2; job=ChainJob(OUTPUT/("gpu_"+TAG)/name,runner)
    job.texture("color",rgba(w,h,.2)); motion=rgba(w,h,0); motion[...,0]=mvx
    job.texture("motion",motion); job.texture("depth",np.full((h,w),10,np.float32),format=41)
    aux=np.zeros((hh,hw,2),np.float16); aux[...,0]=10; aux[...,1]=10
    job.texture("prev_aux",aux,format=34); job.texture("prev_key",rgba(hw,hh,.4,alpha=.2))
    ka=np.zeros((hh,hw,2),np.float16); ka[...,0]=10; ka[...,1]=1
    job.texture("prev_ka",ka,format=34)
    for name2,fmt in [("cur",10),("key",10),("aux",34),("ka",34)]:
        job.texture(name2,size=(hw,hh),format=fmt,writable=True,readback=name2=="aux")
    cb=np.array([w,h,hw,hh,.01,32,0,1],np.float32)
    job.compute(name,SH/"FSRDPostFlickPrepare_Shader.cso",cb.tobytes(),["color","motion","depth","prev_aux","prev_key","prev_ka"],["cur","key","aux","ka"],groups=((hw+7)//8,(hh+7)//8,1))
    out,meta=job.run(keep_staging=False); a=out["aux"][...,0].astype(np.float32)
    return dict(min_age=float(a.min()),max_age=float(a.max()),nonzero=int(np.count_nonzero(a)),pixels=hw*hh)
def glass_case(name,mode,k=.5):
    w=h=8; job=ChainJob(OUTPUT/("gpu_"+TAG)/name,runner); job.texture("black",rgba(w,h,0,0))
    mask=rgba(w,h,0,1/3); mask[...,0]=.5;mask[...,1]=1
    job.texture("normal",mask);job.texture("depth",np.full((h,w),10,np.float32),format=41)
    job.raw("tiles",np.array([1,0,0,0,0,0],np.uint32));job.texture("base",rgba(w,h,.2))
    dec=rgba(w,h,0,0);dec[...,0]=.8;job.texture("decision",dec)
    job.texture("out",rgba(w,h,.8),writable=True,readback=True)
    cb=np.zeros(20,np.float32);cb[:4]=[w,h,1/w,1/h];cb[16]=k;cb.view(np.uint32)[17]=mode
    srvs=["black"]*14;srvs[5]="normal";srvs[6]="depth";srvs[9]="tiles";srvs[10]="base";srvs[11]="decision"
    job.compute(name,SH/"FSRDNrdFlatSelectApply_Shader.cso",cb.tobytes(),srvs,["out",-1,-1],groups=(1,1,1))
    out,meta=job.run(keep_staging=False)
    return dict(rgb=list(map(float,out["out"][4,4,:3])),min=float(out["out"][...,0].min()),max=float(out["out"][...,0].max()))
for name,kwargs in [("apply_inside",{}),("apply_outside",{"shift":20}),("apply_nohistory",{"hist":0}),("apply_wrongdepth",{"depth":11}),("apply_strength0",{"strength":0}),("apply_odd",{"w":65,"h":33})]:
    result[name]=apply_case(name,**kwargs);print(name,json.dumps(result[name]),flush=True)
for name,mvx in [("age_inside",0),("age_outside_right",1),("age_outside_left",-1)]:
    result[name]=prepare_case(name,mvx);print(name,json.dumps(result[name]),flush=True)
for mode in [0,1,2]:
    name="glass_mode"+str(mode);result[name]=glass_case(name,mode);print(name,json.dumps(result[name]),flush=True)
base=np.array(result["glass_mode0"]["rgb"]);rr=np.array(result["glass_mode1"]["rgb"])
result["glass_exact_half_expected"]=((base+rr)*.5).tolist()
result["verdict"]={
"outside_recall_wrongly_changed":result["apply_outside"]["changed"]>0,
"age_outside_wrongly_mature":result["age_outside_right"]["nonzero"]>0,
"odd_border_inert":result["apply_odd"]["last_col"]==[float(np.float16(.2))],
"glass_midpoint_wrong":float(np.max(abs(np.array(result["glass_mode2"]["rgb"])-(base+rr)*.5)))>.01,
"nohistory_control_identity":result["apply_nohistory"]["changed"]==0,
"depth_control_identity":result["apply_wrongdepth"]["changed"]==0,
"strength_control_identity":result["apply_strength0"]["changed"]==0}
(OUTPUT/("gpu_results_"+TAG+".json")).write_text(json.dumps(result,indent=2),encoding="utf8")
print("VERDICTS",json.dumps(result["verdict"]),flush=True)

checks={
"inside_active":result["apply_inside"]["changed"]==2048,
"outside_identity":result["apply_outside"]["changed"]==0,
"age_inside_matures":result["age_inside"]["min_age"]==11,
"age_right_outside_resets":result["age_outside_right"]["max_age"]==0,
"age_left_outside_resets":result["age_outside_left"]["max_age"]==0,
"odd_row_and_column_covered":result["apply_odd"]["changed"]==result["apply_odd"]["pixels"],
"glass_midpoint_exact":float(np.max(abs(np.array(result["glass_mode2"]["rgb"])-(base+rr)*.5)))<.001,
"nohistory_identity":result["apply_nohistory"]["changed"]==0,
"depth_identity":result["apply_wrongdepth"]["changed"]==0,
"strength0_identity":result["apply_strength0"]["changed"]==0}
print("REGRESSION",json.dumps(checks),flush=True)
if args.expect=="fixed":
    bad=[k for k,v in checks.items() if not v]
    print("PASS" if not bad else "FAIL",len(checks)-len(bad),"/",len(checks),"failed=",bad,flush=True)
    sys.exit(bool(bad))
if args.expect=="old":
    assert all(result["verdict"].values())
    print("PASS baseline defects reproduced with 3 identity controls",flush=True)
