"""Frozen synthetic falsifiers and public blind-case export for job06.

All results here are analytic/CPU; the simple staged signals do not model AMD
RR. Diagnosis is conditional on independent witnesses absent in real captures.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import numpy as np
from support_tracer import (previous_coordinates, sample_previous, metric_sequence,
                            diagnose, confidence_interval, abstain_identity)
from synthetic_scenes import SceneConfig, make_scene, intervene

# Frozen before running experiments. Holdout changes trajectory AND noise family.
TRAIN_SEEDS=tuple(range(100,108))
HOLDOUT_SEEDS=tuple(range(900,908))
THRESHOLDS=(.1,.25,.5)
TRAIN=SceneConfig()
HOLDOUT=SceneConfig(trajectory="curved_reentry",noise_family="salt_poisson",camera="moving")


def _erode(mask):
    return np.lib.stride_tricks.sliding_window_view(np.pad(mask,1), (3,3)).all(axis=(-1,-2))


def fixed_geometry_masks(scene, virtual=False):
    """Analytic visibility masks frozen from oracle geometry, never a candidate."""
    m=scene["truth_mask"]
    motion=scene["oracle_virtual_motion"] if virtual else scene["oracle_motion"]
    masks=np.zeros_like(m)
    for t in range(1,len(m)):
        qx,qy,_=previous_coordinates(motion[t],scene["crop_origins"][t],scene["crop_origins"][t-1],scene["render_extent"])
        sample,inside=sample_previous(m[t-1].astype(float),qx,qy)
        masks[t]=_erode(m[t]) & inside & (sample>1-1e-9)
        if virtual: masks[t] &= scene["virtual_feature_mask"][t]
    return masks


def geometry_residual(field, motion, origins, extent, fixed_mask):
    errors=[];invalid=0;count=0
    for t in range(1,len(field)):
        qx,qy,_=previous_coordinates(motion[t],origins[t],origins[t-1],extent)
        previous,inside=sample_previous(field[t-1],qx,qy)
        mask=fixed_mask[t]
        usable=inside & np.isfinite(previous).all(-1)
        residual=np.hypot(previous[...,0]-field[t,...,0],previous[...,1]-field[t,...,1])
        # Do not improve a candidate by dropping its out-of-crop history. Its
        # failure contributes a documented full-render-diagonal penalty.
        residual=np.where(usable,residual,float(np.hypot(*extent)))
        errors.extend(residual[mask].tolist())
        invalid+=int((mask&~usable).sum());count+=int(mask.sum())
    return {"mean_px":float(np.mean(errors)) if errors else None,
            "p90_px":float(np.quantile(errors,.9)) if errors else None,
            "fixed_pixels":count,"invalid_samples":invalid}


def observations(scene):
    mask=scene["truth_mask"]
    geometry=geometry_residual(scene["geometry"],scene["motion"],scene["crop_origins"],scene["render_extent"],fixed_geometry_masks(scene))
    virtual=None
    if np.any(scene["hit_distance"][mask]>0):
        virtual=geometry_residual(scene["virtual_geometry"],scene["virtual_motion"],scene["crop_origins"],scene["render_extent"],fixed_geometry_masks(scene,True))["mean_px"]
    def outside(value):
        total=float(value.sum())
        return float(value[~mask].sum()/total) if total>0 else 0.
    true_count=int(mask.sum())
    return {"evidence_domain":"analytic_synthetic","independent_geometry":bool(scene.get("independent_geometry",False)),
            "known_support":bool(scene.get("known_support",False)),
            "guide_authority":bool(scene.get("guide_authority",False)),
            "geometry_error_px":geometry["mean_px"],"geometry_p90_px":geometry["p90_px"],
            "geometry_fixed_pixels":geometry["fixed_pixels"],"geometry_invalid_samples":geometry["invalid_samples"],
            "raw_offsupport_fraction":outside(scene["raw"]),
            "rr_offsupport_fraction":outside(scene["raw_rr"]),
            "selected_offsupport_fraction":outside(scene["selected"]),
            "raw_support_fraction":float(((scene["raw"]>.25)&mask).sum()/true_count) if true_count else None,
            "virtual_error_px":virtual,
            "alpha_nonpositive_fraction":float((scene["hit_distance"][mask]<=0).mean()) if true_count else None,
            "final_composition_available":False}


def _expected(cause):
    return {"clean":"no_detected_support_error","source_delay":"source_support_error",
            "mv_bias":"transport_error","jitter_error":"transport_error",
            "sparse_source":"sparse_source_no_motion_blame","virtual_mismatch":"virtual_correspondence_error",
            "provider_tail":"provider_stage_tail","selected_tail":"selected_stage_tail",
            "exposure_only":"no_detected_support_error","wrong_guide":"non_identifiable",
            "missing_geometry":"non_identifiable","zero_hit_distance":"no_detected_support_error"}[cause]


def public_payload(scene):
    """Observable tensors, no injected cause/config/seed or oracle motion labels.

    surface_identity and support_truth are deliberately declared synthetic oracle
    observations. They are not claimed to exist in the packaged game capture.
    Missing-authority cases remove them rather than filling a fake answer.
    """
    result={"frame_indices":scene["frame_indices"],"crop_origins":scene["crop_origins"],
            "render_extent":scene["render_extent"],"motion_uv":scene["motion"],
            "virtual_motion_uv":scene["virtual_motion"],"raw":scene["raw"],
            "raw_specular":scene["raw_specular"],"raw_rr":scene["raw_rr"],
            "raw_rr_specular":scene["raw_rr_specular"],"selected":scene["selected"],
            "selected_specular":scene["selected_specular"],"depth":scene["depth"],
            "normal":scene["normal"],"hit_distance":scene["hit_distance"],
            "guide_authority":np.array(bool(scene["guide_authority"]))}
    if scene["independent_geometry"] and scene["known_support"]:
        result.update({"surface_identity":scene["geometry"],"support_truth":scene["truth_mask"],
                       "fixed_geometry_mask":fixed_geometry_masks(scene),
                       "virtual_identity":scene["virtual_geometry"],
                       "fixed_virtual_mask":fixed_geometry_masks(scene,True)})
    return result


def export_blind_cases(directory):
    """Write only anonymized public tensors; return private labels to caller.

    Caller must keep the returned labels from the reviewer until predictions are
    sealed. Two identical incomplete payloads represent an intentional
    observation-equivalence test, not independent captures or noise seeds.
    """
    out=Path(directory);out.mkdir(parents=True,exist_ok=True)
    causes=["selected_tail","sparse_source","mv_bias","clean","virtual_mismatch",
            "source_delay","exposure_only","jitter_error","provider_tail",
            "wrong_guide","zero_hit_distance","missing_geometry"]
    public=[];private={}
    for i,cause in enumerate(causes):
        config=HOLDOUT if i in (1,2,4,5,7) else TRAIN
        scene=make_scene(config,HOLDOUT_SEEDS[i%len(HOLDOUT_SEEDS)],cause)
        case=f"case_{i+1:02d}";path=out/(case+".npz")
        payload=public_payload(scene)
        np.savez_compressed(path,**payload)
        public.append({"case_id":case,"file":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                       "independent_support_and_geometry_present":"support_truth" in payload,
                       "analytic_witnesses_only":True})
        private[case]={"cause":cause,"expected":_expected(cause),"heldout":config==HOLDOUT}
    # Observational equivalence: the same sparse arrays admit missing-sample or
    # delayed-source explanations if independent silhouette/history is absent.
    ambiguous=make_scene(HOLDOUT,907,"sparse_source")
    ambiguous["independent_geometry"]=False;ambiguous["known_support"]=False
    for i,latent in enumerate(("missing_samples_with_correct_motion","unobserved_source_delay_with_same_sparse_observation"),13):
        case=f"case_{i:02d}";path=out/(case+".npz")
        np.savez_compressed(path,**public_payload(ambiguous))
        public.append({"case_id":case,"file":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                       "independent_support_and_geometry_present":False,"analytic_witnesses_only":True})
        private[case]={"cause":latent,"expected":"non_identifiable","heldout":True,"observation_equivalence_pair":True}
    manifest={"schema":"job06.synthetic_blind.v1","gpu_executed":False,"cases":public,
        "coordinates":"clip_loader contract: previous-minus-current full-render UV; crop origins x,y; no added jitter",
        "signal_units":"synthetic linear scalar radiance; source support may be sparse",
        "surface_identity":"Independent analytic local object coordinates (x,y in pixels) and wall world coordinates; channel2 surface ID",
        "virtual_identity":"Independent analytic reflected-feature coordinates; not reconstructed from hit distance",
        "support_truth":"Known analytic physical silhouette; unavailable in supplied game clips",
        "fixed_masks":"Analytic original visible correspondence support, fixed before observed motion mutation",
        "guide_authority":"Whether the geometry witness has independent trusted provenance; false requires abstention",
        "unknowns":"No final game composite. Zero hit distance does not authorize virtual projection. Incomplete cases lack support/history authority.",
        "instructions":"Recover mechanisms from arrays or explicitly report non-identifiability. No injected labels/configuration are published."}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    return private


def run_experiments():
    causes=("clean","source_delay","mv_bias","jitter_error","sparse_source","virtual_mismatch","provider_tail","selected_tail","exposure_only")
    rows=[];aggregates=[]
    for split,config,seeds in (("train",TRAIN,TRAIN_SEEDS),("holdout",HOLDOUT,HOLDOUT_SEEDS)):
        for cause in causes:
            measurements=[]
            for seed in seeds:
                scene=make_scene(config,seed,cause)
                obs=observations(scene);decision=diagnose(obs)
                metrics={};specular_metrics={}
                for threshold in THRESHOLDS:
                    metrics[str(threshold)]=metric_sequence(scene["selected"],scene["truth"],scene["truth_mask"],scene["centres_local"],scene["velocity"],threshold,disocclusion_mask=scene["disocclusion_mask"])["summary"]
                    specular_metrics[str(threshold)]=metric_sequence(scene["selected_specular"],scene["truth_specular"],scene["truth_specular"]>threshold,scene["feature_centres_local"],scene["feature_velocity"],threshold,disocclusion_mask=scene["disocclusion_mask"])["summary"]
                row={"split":split,"cause":cause,"seed":seed,"observations":obs,"diagnosis":decision,
                     "expected":_expected(cause),"correct_or_explicit_abstention":decision["diagnosis"]==_expected(cause),"metrics":metrics,"specular_metrics":specular_metrics}
                rows.append(row);measurements.append(row)
            intervals={};specular_intervals={}
            for threshold in THRESHOLDS:
                intervals[str(threshold)]={key:confidence_interval([r["metrics"][str(threshold)][key] for r in measurements if r["metrics"][str(threshold)][key] is not None]) for key in measurements[0]["metrics"][str(threshold)] if key not in ("fixed_evaluation_pixels","fixed_support_pixels")}
                specular_intervals[str(threshold)]={key:confidence_interval([r["specular_metrics"][str(threshold)][key] for r in measurements if r["specular_metrics"][str(threshold)][key] is not None]) for key in measurements[0]["specular_metrics"][str(threshold)] if key not in ("fixed_evaluation_pixels","fixed_support_pixels")}
            aggregates.append({"split":split,"cause":cause,"correct":sum(r["correct_or_explicit_abstention"] for r in measurements),"total":len(measurements),"seed_ci":intervals,"specular_seed_ci":specular_intervals})
    interventions=[]
    for cause,intervention in (("source_delay","oracle_motion"),("source_delay","oracle_support"),
                              ("mv_bias","oracle_motion"),("mv_bias","oracle_support"),
                              ("provider_tail","current_input_only"),("selected_tail","observe_raw_instead_selected"),
                              ("virtual_mismatch","oracle_virtual")):
        original=make_scene(TRAIN,101,cause);changed=intervene(original,intervention)
        interventions.append({"cause":cause,"diagnostic_only":intervention,
            "before":observations(original),"after":observations(changed),
            "downstream_reexecuted":False,"note":"Only the named input/stage observation is replaced; stored downstream stages are not rerun"})
    controls=[]
    for name,config,cause in (("static_opaque",replace(TRAIN,trajectory="static",rotating=False,opaque=True),"clean"),
                             ("camera_only",replace(TRAIN,trajectory="static",camera="moving",rotating=False),"clean"),
                             ("combined_camera_object",replace(TRAIN,camera="moving"),"clean"),
                             ("slow",replace(TRAIN,trajectory="slow"),"clean"),
                             ("fast",replace(TRAIN,trajectory="fast"),"clean"),
                             ("one_pixel",replace(TRAIN,thin=True,rotating=False),"clean"),
                             ("zero_hit",replace(TRAIN,hit_distance=0),"zero_hit_distance"),
                             ("low_hit",replace(TRAIN,hit_distance=1e-6),"clean"),
                             ("wrong_guide",TRAIN,"wrong_guide"),
                             ("missing_geometry",TRAIN,"missing_geometry"),
                             ("light_1.1",replace(TRAIN,trajectory="static",rotating=False,moving_crop=False,light_step=1.1),"clean"),
                             ("light_1.25",replace(TRAIN,trajectory="static",rotating=False,moving_crop=False,light_step=1.25),"clean"),
                             ("light_1.4",replace(TRAIN,trajectory="static",rotating=False,moving_crop=False,light_step=1.4),"clean")):
        scene=make_scene(config,103,cause);obs=observations(scene)
        preserved=abstain_identity(scene["selected"])
        alpha=abstain_identity(scene["alpha"])
        composite=scene["background"]+scene["selected"]
        copied_composite=abstain_identity(composite)
        detail=scene["detail_mask"]
        edges=detail[:,:,1:]&detail[:,:,:-1]
        before_detail=np.abs(np.diff(composite,axis=2))[edges].sum()
        after_detail=np.abs(np.diff(copied_composite,axis=2))[edges].sum()
        raw_level=float(scene["raw"].sum());selected_level=float(preserved.sum())
        controls.append({"name":name,"observations":obs,"diagnosis":diagnose(obs),
            "candidate_identity_bits":preserved.tobytes()==scene["selected"].tobytes(),
            "alpha_identity_bits":alpha.tobytes()==scene["alpha"].tobytes(),
            "detail_identity_error":float(np.max(np.abs(copied_composite[detail]-composite[detail]))) if detail.any() else None,
            "static_text_composite_identity_bits":copied_composite.tobytes()==composite.tobytes(),
            "static_text_mask_pixels":int(detail.sum()),
            "retained_static_text_detail_ratio":float(after_detail/before_detail) if before_detail>0 else None,
            "step":config.light_step,"candidate_to_baseline_light_energy_ratio":selected_level/raw_level if raw_level else None})
    return {"schema":"job06.synthetic_experiments.v1","gpu_executed":False,"executor":"CPU NumPy analytic model",
            "freeze":{"train":TRAIN.__dict__,"holdout":HOLDOUT.__dict__,"train_seeds":TRAIN_SEEDS,"holdout_seeds":HOLDOUT_SEEDS,"thresholds":THRESHOLDS,
                      "diagnostic_thresholds":{"geometry_px":.45,"source_offsupport_fraction":.12,"stage_tail_excess":.08,"sparse_coverage":.65}},
            "rows":rows,"aggregates":aggregates,"interventions":interventions,"controls":controls,
            "candidate":"diagnostic abstention, bit-preserving identity",
            "metric_domains":{"metrics":"diffuse-like scalar support, analytic physical silhouette", "specular_metrics":"specular scalar radiance occupancy; target threshold applied to analytic truth, reflected-feature velocity used for signed lag/tails"},"recommendation":"keep_as_research",
            "limits":["Analytic support/geometry witnesses are absent in real bottle capture",
                      "Stage arrays are synthetic interventions, not AMD RR",
                      "Bootstrap confidence intervals summarize independent seeds; trajectories are separate strata",
                      "No game improvement or GPU timing claimed",
                      "One-pixel structures can have zero conservative bilinear geometry support and require abstention"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    result=run_experiments()
    payload=json.dumps(result,indent=2,allow_nan=False)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(payload)
    else: print(payload)


if __name__=="__main__": main()
