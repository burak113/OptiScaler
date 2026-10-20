"""Byte-level source/data inventory; all statistics use unmodified fixture arrays."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import numpy as np

HERE=Path(__file__).resolve().parent
PACKAGE=HERE.parents[1]
REPO=PACKAGE.parents[1]
PRE=REPO/"OptiScaler/shaders/fsrd_preprocess/precompile"
SHADERS=["FSRDColourTrackStats","FSRDColourTrackTrack","FSRDColourTrackApply",
         "FSRDPostMotionAnchorStatsRecall","FSRDPostMotionAnchorGain",
         "FSRDPostMotionAnchorApply","FSRDNrdPostMotionAnchorStatsRecall",
         "FSRDNrdPostMotionAnchorGain"]


def sha(data):return hashlib.sha256(data).hexdigest()


def file_info(path):
    data=path.read_bytes()
    return {"path":path.relative_to(REPO).as_posix(),"bytes":len(data),"sha256":sha(data)}


def source_inventory():
    compiler_paths=[REPO/"OptiScaler/shaders/shader_tools"/name
                    for name in ("dxc.exe","dxcompiler.dll","dxil.dll")]
    compiler={"bundled_files":[file_info(p) for p in compiler_paths],
        "fresh_compilation_executed":False,"executable_invoked":None,
        "reason":"Bundled compiler is Windows PE; current environment Linux. No GPU/DXC result is invented.",
        "native_profile":{"target":"cs_6_6","entry":"CSMain","flags":["-HV","2021","-O3","-enable-16bit-types"]},
        "combined_colour_profile":{"target":"cs_6_2","entry":"CSMain","flags":["-enable-16bit-types","-O3","-Qstrip_debug","-Qstrip_reflect"]}}
    sources=[]
    for name in SHADERS:
        entry={"name":name,"source":file_info(PRE/(name+".hlsl")),
               "cso":file_info(PRE/(name+"_Shader.cso")),"header":file_info(PRE/(name+"_Shader.h"))}
        raw=(PRE/(name+"_Shader.h")).read_text()
        body=raw[raw.index("= {")+3:raw.rindex("}")]
        payload=bytes(int(x,16) for x in re.findall(r"0x([0-9a-fA-F]{2})",body))
        entry["embedded_cso_sha256"]=sha(payload)
        entry["embedded_matches_cso"]=payload==(PRE/(name+"_Shader.cso")).read_bytes()
        entry["source_line_endings"]="CRLF" if b"\r\n" in (PRE/(name+".hlsl")).read_bytes() else "LF"
        sources.append(entry)
    other=["OptiScaler/shaders/fsrd_preprocess/FSRDColourTrackConstants.h",
           "OptiScaler/shaders/fsrd_preprocess/FSRDPostMotionAnchorConstants.h",
           "OptiScaler/shaders/fsrd_preprocess/FSRDNrdPostMotionAnchor_Dx12.h",
           "OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp",
           "OptiScaler/shaders/fsrd_preprocess/precompile/FSRDFlatDetailCommon.hlsli",
           "OptiScaler/shaders/shader_tools/build_fsrd_shader.py",
           "OptiScaler/shaders/shader_tools/tests/test_fsrd_shader_artifact_contract.py"]
    return {"base_tag":"astra-handoff-20261020",
            "resolved_tag_commit":subprocess.check_output(["git","rev-parse","astra-handoff-20261020^{commit}"],cwd=REPO,text=True).strip(),
            "compiler":compiler,"shaders":sources,"related_sources":[file_info(REPO/p) for p in other]}


def array_stats(a):
    out={"shape":list(a.shape),"dtype":a.dtype.str,"raw_bytes":a.nbytes,"raw_sha256":sha(a.tobytes())}
    if a.dtype.kind=="f":
        finite=np.isfinite(a)
        out["nonfinite_count"]=int((~finite).sum())
        values=a[finite].astype(np.float64)
        out["zero_count"]=int(np.count_nonzero(a==0))
        out["finite_min"]=float(values.min()) if values.size else None
        out["finite_max"]=float(values.max()) if values.size else None
    return out


def clip_inventory():
    clips=[]
    for name in ("bottle_track7","foliage23","facade16"):
        path=PACKAGE/"fixtures/clips"/(name+".npz")
        meta=json.loads(path.with_suffix(".json").read_text())
        with np.load(path,allow_pickle=False) as f:
            width,height=map(int,f["render_extent"])
            frames=f["frame_indices"].tolist();origins=f["crop_origin_render"].tolist()
            h,w=f["input_depth"].shape[1:]
            yy,xx=np.indices((h,w),dtype=np.float32)
            positions=np.stack((xx,yy),-1)
            support=[]
            for j,frame in enumerate(frames):
                if j==0:mask=np.zeros((h,w),bool)
                else:
                    q=positions+np.array(origins[j],np.float32)+f["input_motion"][j,...,:2].astype(np.float32)*np.array([width,height],np.float32)-np.array(origins[j-1],np.float32)
                    # Use the packaged clip's stricter fixed bilinear support,
                    # not a candidate's tap/sampler-dependent support.
                    mask=np.isfinite(q).all(-1)&(q[...,0]>=0)&(q[...,0]<w-1)&(q[...,1]>=0)&(q[...,1]<h-1)
                support.append({"frame":int(frame),"total_pixels":h*w,"supported_pixels":int(mask.sum()),
                                "unsupported_pixels":int((~mask).sum()),"mask_sha256":sha(mask.tobytes())})
            lobes={}
            for key in ("input_diffuse","input_specular","raw_rr_diffuse","raw_rr_specular","selected_rr_diffuse","selected_rr_specular"):
                a=f[key][...,:3].astype(np.float32)
                lum=np.sum(a*np.array([.2126,.7152,.0722],np.float32),-1,dtype=np.float32)
                positive=lum>0
                p99=float(np.percentile(lum,99))
                lobes[key]={"rgb_zero_fraction":float(np.mean(a==0)),
                    "luma_zero_fraction":float(np.mean(lum==0)),"luma_p50":float(np.median(lum)),
                    "luma_p99":p99,"luma_max":float(lum.max()),
                    "energy_above_p99_fraction":float(lum[lum>p99].sum(dtype=np.float64)/max(lum.sum(dtype=np.float64),1e-30))}
            clips.append({"fixture":name,"file":file_info(path),"manifest":file_info(path.with_suffix('.json')),
                "capture":meta["source_capture_uuid"],"frame_indices":frames,"render_extent_xy":[width,height],
                "crop_extent_xy":[w,h],"crop_origins_render_xy":origins,"partial_history":True,
                "albedo_present":any("albedo" in k for k in f.files),"ground_truth":meta["ground_truth"],
                "original_material_codes":np.unique(f["recovery_original_normal_roughness"]>>30).tolist(),
                "units":meta["storage_contract"],"coordinates":meta["coordinate_contract"],
                "fixed_support_by_frame":support,"lobes":lobes,
                "arrays":{k:array_stats(f[k]) for k in f.files}})
    return clips


def fixture_inventory():
    paths=sorted(p for base in [PACKAGE/"portable/anchor/fixtures",PACKAGE/"portable/colour/fixtures",PACKAGE/"fixtures/glass"]
                 for p in base.rglob("*.npz"))
    data=[]
    for p in paths:
        with np.load(p,allow_pickle=False) as f:
            data.append({"file":file_info(p),"arrays":{k:array_stats(f[k]) for k in f.files}})
    glass=json.loads((PACKAGE/"fixtures/glass/manifest.json").read_text())
    return {"archives":data,"clips":clip_inventory(),"glass_scope":{
        k:glass[k] for k in ("capture_uuid","frames","fixture_common_mask_pixels",
        "full_roi_common_mask_pixels_separate_evidence","fixture_crop_in_original_roi_xyxy",
        "reference_warning","alignment","geometry_provenance")},
        "limits":["No albedo in chronological clips","No pre-start history","No original native pre-store atomic buffer",
                  "No full-colour GPU intermediate tensors or exact gate map","No converged same-pose truth",
                  "Glass data is aligned; it does not supply every native signal role"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=HERE/"evidence")
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    for filename,data in (("source_inventory.json",source_inventory()),("data_inventory.json",fixture_inventory())):
        (args.output/filename).write_text(json.dumps(data,indent=2,allow_nan=False)+"\n")
        print(filename)


if __name__=="__main__":main()
