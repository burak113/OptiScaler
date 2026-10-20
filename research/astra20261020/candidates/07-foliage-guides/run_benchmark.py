#!/usr/bin/env python3
"""Run the frozen CPU mixed-coverage experiment and write strict JSON evidence."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import numpy as np

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"src"))
from foliage_guides import observe_guides, pack_normal_roughness, unpack_normal_roughness, normalize
from synthetic_scene import SceneConfig, generate_scene, identical_observations
from proxy_metrics import run_proxy, metrics, paired_light_response, diagnostic_metrics

MODES=("raw_half_inputs","diagnostic_identity","single_dominant_guide",
       "perfect_unquantized_dominant_guide","flattened_normals","misdecoded_normals",
       "cosine_support_consumer","oracle_layer_guides_single_motion","oracle_layer_guides_layer_motion")


def configs(protocol:dict,reference_only:bool=False)->list[SceneConfig]:
    base=SceneConfig(seed=protocol["development_seed"])
    if reference_only:return [base]
    out=[base]
    for family,values in protocol["ofat"].items():
        for v in values:
            out.append(replace(base,name=f"{family}_{v}",family=family,**{family:v}))
    fixed=dict(camera_vx=0,camera_vy=0,object_vx=0,object_vy=0,jitter_amplitude=0)
    out.extend([replace(base,name="fixed_coverage_independent",family="coverage_motion",**fixed),
                replace(base,name="fixed_coverage_correlated",family="lighting_correlation",noise_rho=.95,**fixed),
                replace(base,name="rigid_facade_static",family="rigid_control",kind="facade",**fixed),
                replace(base,name="rigid_facade_moving",family="rigid_control",kind="facade"),
                replace(base,name="moderate_light_125",family="light_response",light_step=1.25)])
    # Seed, phase/orientation, and trajectory were jointly frozen as unseen cases.
    # They are not presented as OFAT causal interventions.
    for i,seed in enumerate(protocol["holdout_seeds"]):
        motion=protocol["holdout_trajectories_pixels_per_frame"][i]
        c=replace(base,name=f"holdout_{seed}",family="heldout_trajectory",split="holdout",seed=seed,
                  orientation=protocol["holdout_orientations_degrees"][i],phase=protocol["holdout_phases"][i],
                  object_vx=motion[0],object_vy=motion[1],noise_rho=(.0,.5,.95)[i])
        out.extend([c,replace(c,name=f"holdout_facade_{seed}",kind="facade",family="heldout_rigid"),
                    replace(c,name=f"holdout_thin_{seed}",thickness=.3,family="heldout_thin")])
    return out


def decoder_calibration()->dict:
    values=np.array([[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1],
                     [.2,.5,.84],[-.8,.1,.6],[.2,-.3,-.9],[-.3,-.4,-.8]],np.float32)
    values=normalize(values)
    words=pack_normal_roughness(values,.35,0)
    decoded=unpack_normal_roughness(words)[0]
    bad=normalize(np.stack([(words&1023)/1023,((words>>10)&1023)/1023,((words>>20)&1023)/1023],axis=-1)*2-1)
    angle=lambda v:np.degrees(np.arccos(np.clip(np.sum(values*v,axis=-1),-1,1)))
    return {"scope":"analytic homogeneous known normals, oct quantization only",
            "normal_count":len(values),"correct_max_degrees":float(angle(decoded).max()),
            "correct_mean_degrees":float(angle(decoded).mean()),
            "deliberately_misdecoded_mean_degrees":float(angle(bad).mean()),
            "material_zero_preserved":bool(np.all(unpack_normal_roughness(words)[2]==0))}


def collision_result()->dict:
    case=identical_observations()
    a=observe_guides(case["frames"][1],case["frames"][0],enabled=True)
    # Both worlds provide exactly the same observable history and metadata.
    b=observe_guides(case["frames"][1],case["frames"][0],enabled=True)
    return {"construction":"dominant front layer identical; invisible minority layer radiance/motion differs",
            "guide_sha256":case["guide_sha256"],"visible_front_fraction":case["visible_front_fraction"],
            "hidden_motion_pixels":case["hidden_motion_pixels"],
            "max_true_rgb_difference":float(np.abs(case["plane_radiance"]-case["mixture_radiance"]).max()),
            "observer_outputs_identical":all(np.array_equal(getattr(a,k),getattr(b,k)) for k in a.__dataclass_fields__),
            "supported_mean_multiplier":float(a.experimental_history_multiplier[a.temporal_supported].mean()),
            "conclusion":"A guide-only observer cannot identify the hidden mixture; low uncertainty does not establish homogeneous coverage."}


def summary(cases:list[dict])->dict:
    answer={}
    for split in ("development","holdout"):
        items=[x for x in cases if x["config"]["split"]==split]
        if not items:continue
        answer[split]={"case_count":len(items)}
        for mode in MODES:
            ms=[x["methods"][mode] for x in items]
            answer[split][mode]={}
            for metric in ("grain_highpass_rms","sparkle_abs_error_p99","flicker_residual_difference_rms",
                           "detail_gradient_transfer","false_history_support_fraction","cross_layer_mixing_weight",
                           "fixed_score_lower_better","paired_light_response_first_four_frames"):
                values=[m[metric] for m in ms if m.get(metric) is not None]
                answer[split][mode][metric]=({"mean":float(np.mean(values)),"min":float(np.min(values)),
                                             "max":float(np.max(values)),"p90":float(np.quantile(values,.9))} if values else None)
        ratios=[]
        for case in items:
            base=case["methods"]["single_dominant_guide"];cand=case["methods"]["cosine_support_consumer"]
            ratios.append({"case":case["config"]["name"],
                           "sparkle_ratio":cand["sparkle_abs_error_p99"]/max(base["sparkle_abs_error_p99"],1e-20),
                           "flicker_ratio":cand["flicker_residual_difference_rms"]/max(base["flicker_residual_difference_rms"],1e-20),
                           "detail_transfer_delta":cand["detail_gradient_transfer"]-base["detail_gradient_transfer"],
                           "cross_layer_mixing_delta":cand["cross_layer_mixing_weight"]-base["cross_layer_mixing_weight"]})
        answer[split]["hypothetical_consumer_pairwise"]=ratios
        answer[split]["worst_consumer_sparkle_case"]=max(ratios,key=lambda x:x["sparkle_ratio"])
        answer[split]["worst_consumer_flicker_case"]=max(ratios,key=lambda x:x["flicker_ratio"])
    return answer


def input_groups(cases:list[dict])->dict:
    groups={}
    for case in cases:
        groups.setdefault(case["manifest"]["inputs_sha256"],[]).append(case["config"]["name"])
    return {"protocol_row_count":len(cases),"unique_input_count":len(groups),
            "duplicate_input_groups":{key:names for key,names in groups.items() if len(names)>1},
            "interpretation":"OFAT reference settings recur as calibration rows; protocol rows are not independent samples. Holdout rows have distinct frozen seeds/trajectories."}


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,default=ROOT/"evidence"/"synthetic_benchmark.json")
    p.add_argument("--reference-only",action="store_true",help="Smoke run only; not the full held-out experiment")
    p.add_argument("--executor",default="CPU Python process; see execution receipt",help="Actual executor attribution for this run")
    args=p.parse_args()
    started=time.perf_counter()
    protocol_path=ROOT/"experiments"/"protocol.json"
    protocol=json.loads(protocol_path.read_text())
    allcases=configs(protocol,args.reference_only)
    results=[]
    for index,c in enumerate(allcases):
        scene=generate_scene(c)
        no_step=generate_scene(replace(c,light_step=1.0))
        outputs={mode:run_proxy(scene,mode) for mode in MODES}
        reference_outputs={mode:run_proxy(no_step,mode) for mode in MODES}
        method_results={}
        for mode in MODES:
            m=metrics(scene,outputs[mode])
            m["paired_light_response_first_four_frames"]=paired_light_response(scene,outputs[mode],no_step,reference_outputs[mode])
            method_results[mode]=m
        results.append({"config":asdict(c),"manifest":scene.manifest,"methods":method_results,
                        "diagnostic":diagnostic_metrics(scene),"all_masks_frozen_before_methods":True,
                        "primary_candidate_rgb_bitwise_identity":bool(np.array_equal(outputs["diagnostic_identity"].rgb,scene.observed)),
                        "alpha_values_preserved":{"diffuse":bool(np.all(scene.diffuse_rgba[...,3]==np.float16(3.25))),
                                                   "specular":bool(np.all(scene.specular_rgba[...,3]==np.float16(7.5)))}})
        if index==0:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(args.output.parent/"synthetic_reference_arrays.npz",
                truth=scene.truth,base_input=scene.observed,
                single_guide_cpu_proxy=outputs["single_dominant_guide"].rgb,
                flattened_cpu_proxy=outputs["flattened_normals"].rgb,
                cosine_consumer_cpu_proxy=outputs["cosine_support_consumer"].rgb,
                layer_oracle_cpu_proxy=outputs["oracle_layer_guides_layer_motion"].rgb,
                coverage=scene.coverage,packed_normals=np.stack([g.packed_normal_roughness for g in scene.frames]),
                depths=np.stack([g.depth for g in scene.frames]),
                **{"mask_"+key:value for key,value in scene.masks.items()})
        print(f"[{index+1}/{len(allcases)}] {c.name}",flush=True)
    payload={"schema":"job07-synthetic-benchmark-v1","stage":"CPU synthetic model only",
             "executor":args.executor,"gpu_executed":False,
             "python":platform.python_version(),"numpy":np.__version__,
             "protocol_sha256":hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
             "source_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted((ROOT/"src").glob("*.py"))},
             "reference_only":args.reference_only,"case_count":len(results),
             "elapsed_seconds":time.perf_counter()-started,
             "guide_observer":"Default OFF; no RGB/normal/depth/material/roughness/alpha mutations",
             "consumer_scope":"Hypothetical CPU temporal-filter weight ablation; not an AMD API or proposed live host change",
             "oracle_scope":"Uses hidden per-layer radiance and exact current coverage; background normal/depth are layer moments. Not deployable or per-sample AMD truth.",
             "decoder_calibration":decoder_calibration(),"identifiability_collision":collision_result(),
             "cases":results,"input_groups":input_groups(results),
             "summary_scope":"protocol-row aggregates; duplicated OFAT reference rows retain their per-family context",
             "summary":summary(results),
             "summary_unique_inputs":summary(list({x["manifest"]["inputs_sha256"]:x for x in reversed(results)}.values())),
             "acceptance":"keep as research; diagnostic valid, captured causal efficacy and native GPU/game effect unproven",
             "performance_ms":None,"gpu_performance_ms":None}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"output":str(args.output.relative_to(ROOT)) if args.output.is_relative_to(ROOT) else args.output.name,
                      "case_count":len(results),"elapsed_seconds":payload["elapsed_seconds"]},allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
