"""Frozen-population CPU calibration and numerical interventions, never GPU runs.

Run from any working directory: python <candidate>/calibrate.py --output evidence
The portable modules are loaded into private module objects. Their files remain
unchanged; each intervention replaces an operation in its own private instance.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import sys

import numpy as np

from numerical_contract import __version__
from numerical_contract import sampling as S
from numerical_contract import coordinates as C
from numerical_contract.storage import fp16_preimage_f32, store_fp16, NonIdentifiableError
from numerical_contract.guards import colour_history_valid, require_unique_observable

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
REPO = PACKAGE.parents[1]
COLOUR = PACKAGE / "portable/colour"
ANCHOR = PACKAGE / "portable/anchor"


def module_from_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def differences(actual, reference, mask=None):
    a, b = np.asarray(actual), np.asarray(reference)
    if a.shape != b.shape:
        raise ValueError("comparison must preserve the frozen population")
    if mask is not None:
        mask = np.asarray(mask, dtype=bool)
        a, b = a[mask], b[mask]
    if not a.size or not (np.isfinite(a).all() and np.isfinite(b).all()):
        raise ValueError("empty/nonfinite comparison requires explicit unsupported handling")
    error = np.abs(a.astype(np.float64)-b.astype(np.float64))
    return {"elements": int(a.size), "max_abs": float(error.max()),
            "p50_abs": float(np.percentile(error, 50)),
            "p95_abs": float(np.percentile(error, 95)),
            "p99_abs": float(np.percentile(error, 99)),
            "nonzero_error_count": int(np.count_nonzero(error)),
            "array_equal": bool(np.array_equal(a,b))}


def colour_calibration():
    with np.load(COLOUR/"fixtures/soft2_gpu_87ee63.npz", allow_pickle=False) as file:
        f = {k:file[k] for k in file.files}
    args = [f[k] for k in ("input_rgb", "rr_rgb", "depth", "normals_oct", "motion_px")]
    results, states = {}, {}
    profiles = [("frozen", None, "rtz"), ("ideal_sampler64", "ideal", "rtz"),
                ("source_sampler32", "source", "rtz"),
                ("observed_fraction8", "observed", "rtz"),
                ("rne_stores_source32", "source", "rne"),
                ("rne_stores_fraction8", "observed", "rne")]
    for name, sampler_mode, rounding in profiles:
        cp = module_from_file("_contract_colour_"+name, COLOUR/"colour_portable.py")
        if sampler_mode:
            def bilinear(v, x, y, mode=sampler_mode):
                return S.bilinear_texel(v, np.stack((x,y),-1), mode=mode,
                    interpolation="weighted_sum").require_supported()
            cp.bilinear = bilinear
        if rounding == "rne":
            cp.half_rtz = lambda value: store_fp16(value, rounding="rne")
        model = cp.rejected_soft2_model()
        model.hist = f["prev_history"].copy()
        output, data = model.frame(*args)
        soft2 = cp.rejected_soft2_apply(args[1], args[2], args[3], data)
        stats = np.concatenate((data["colour"],data["z"][...,None]),-1)
        packed = cp.half_rtz(cp.pack_new(cp.box(args[3],8)))
        ms = cp.half_rtz(cp.box(args[4],8))
        yy,xx=np.mgrid[:64,:64].astype(np.float32)
        px,py=xx+ms[...,0]/8, yy+ms[...,1]/8
        uv=np.stack(((px+.5)/64,(py+.5)/64),-1)
        sampled=cp.bilinear(f["prev_history"],px,py)
        # Preserve the private Model's exact mixed-dtype predicate. Only its
        # sampler changes in ideal_sampler64; expected/tolerance remain f32.
        expected_depth=data["z"]+ms[...,2]
        valid=(np.all(uv>=0,axis=-1)&np.all(uv<=1,axis=-1)&(abs(sampled[...,3])>1e-9))
        valid&=abs(sampled[...,3]-expected_depth)<=.02*np.maximum(abs(expected_depth),.001)
        if sampler_mode!='ideal':
            np.testing.assert_array_equal(valid,colour_history_valid(sampled[...,3],data["z"],ms[...,2],uv))
        arrays={"stats":stats,"history":model.hist,"gain":data["g"],
                "packed_normal":packed,"bilinear_output":output,"soft2_output":soft2,
                "sampled_history":sampled,"validity":valid}
        states[name]=arrays
        expected={"stats":"expected_stats","history":"expected_history", "gain":"expected_gain",
                  "packed_normal":"expected_packed_normal", "bilinear_output":"expected_bilinear",
                  "soft2_output":"expected_soft2"}
        results[name]={"sampler_profile":sampler_mode,"store_model":rounding,
            "vs_exported_expected":{k:differences(arrays[k],f[v]) for k,v in expected.items()},
            "valid_cells":int(valid.sum()),"validity_sha256":digest(valid),
            "sampled_history_sha256":digest(sampled)}
    baseline=states["frozen"]
    for name in states:
        arrays=states[name]
        results[name]["vs_frozen"]={k:differences(arrays[k],baseline[k]) for k in arrays if k!="validity"}
        changed=np.argwhere(arrays["validity"] != baseline["validity"])
        results[name]["changed_validity_count"]=len(changed)
        results[name]["changed_validity_yx"]=changed.tolist()
    # Source-compatible overlap is a separate identifiable observation. Never
    # claim those recovered bits are absent merely because this NPZ omits them.
    from adversary_controls import overlap_recovery
    overlap,known_mask,recovered_rr=overlap_recovery(return_arrays=True)
    # Same rounded full tensor; generic endpoint witnesses follow first.
    cp=module_from_file("_contract_colour_witness",COLOUR/"colour_portable.py")
    model=cp.rejected_soft2_model();model.hist=f["prev_history"].copy()
    _,data=model.frame(*args)
    interval=fp16_preimage_f32(f["rr_rgb"],rounding="rtz")
    first,second=interval.lower,interval.upper
    same=np.array_equal(cp.half_rtz(first).view(np.uint32),cp.half_rtz(second).view(np.uint32))
    if not same:raise AssertionError("witness must have identical stored data")
    out1=cp.rejected_soft2_apply(first,args[2],args[3],data)
    out2=cp.rejected_soft2_apply(second,args[2],args[3],data)
    try:require_unique_observable([out1,out2])
    except NonIdentifiableError:rejected=True
    else:rejected=False
    changed=np.argwhere(out1!=out2)
    selected=changed[0].tolist() if len(changed) else None
    witness={"identical_exported_rr_rgb":same,"exact_reconstruction_rejected":rejected,
        "prestore1_recipe":"fp16_preimage_f32(rr_rgb,rounding='rtz').lower",
        "prestore2_recipe":"fp16_preimage_f32(rr_rgb,rounding='rtz').upper",
        "output_difference":differences(out2,out1),"first_different_yxc":selected,
        "outputs_at_first":None if selected is None else [float(out1[tuple(selected)]),float(out2[tuple(selected)])],
        "prestore1_sha256":digest(first),"prestore2_sha256":digest(second),
        "note":"The interval endpoints are witnesses, not a bound on all nonlinear JBU outputs. No attempt to recover the original missing low bits."}
    # Reviewer required compatibility with the actual captured-half D+S domain.
    # Arbitrary float32 bin endpoints need not be the sum of two FP16 lobes.
    with np.errstate(over="ignore",invalid="ignore"):
        next_half=np.nextafter(first.astype(np.float16),np.float16(np.inf)).astype(np.float32)
        delta=(next_half-first)*np.float32(.5)
    delta=np.where(np.isfinite(delta)&(delta>=np.float32(2**-24)),delta,np.float32(0))
    np.testing.assert_array_equal(store_fp16(delta,rounding="rne"),delta)
    half_lobe_sum=(first+delta).astype(np.float32)
    np.testing.assert_array_equal(cp.half_rtz(half_lobe_sum).view(np.uint32),f["rr_rgb"].view(np.uint32))
    out_lobes=cp.rejected_soft2_apply(half_lobe_sum,args[2],args[3],data)
    try:require_unique_observable([out1,out_lobes])
    except NonIdentifiableError:lobe_rejected=True
    else:lobe_rejected=False
    lobe_changed=np.argwhere(out1!=out_lobes)
    lobe_pixel=lobe_changed[0].tolist() if len(lobe_changed) else None
    witness["half_lobe_admissible_witness"]={
        "decomposition1":"D=exported rr_rgb (FP16-exact), S=0",
        "decomposition2":"D=exported rr_rgb, S=half-bin step/2 if finite and>=2^-24 else0 (FP16-exact)",
        "all_lobes_nonnegative_fp16":bool(np.all(first>=0) and np.all(delta>=0)),
        "identical_exported_rr_rgb":True,"exact_reconstruction_rejected":lobe_rejected,
        "output_difference":differences(out_lobes,out1),"first_different_yxc":lobe_pixel,
        "outputs_at_first":None if lobe_pixel is None else [float(out1[tuple(lobe_pixel)]),float(out_lobes[tuple(lobe_pixel)])],
        "second_lobe_sha256":digest(delta),"second_sum_sha256":digest(half_lobe_sum),
        "scope":"Two compatible nonnegative captured-half lobe decompositions, not a recovery of the original missing lobes."}
    known_first=first.copy();known_second=half_lobe_sum.copy()
    known_first[known_mask]=recovered_rr[known_mask]
    known_second[known_mask]=recovered_rr[known_mask]
    known_out1=cp.rejected_soft2_apply(known_first,args[2],args[3],data)
    known_out2=cp.rejected_soft2_apply(known_second,args[2],args[3],data)
    try:require_unique_observable([known_out1,known_out2])
    except NonIdentifiableError:known_rejected=True
    else:known_rejected=False
    witness["overlap_constrained_witness"]={
        "exact_reconstruction_rejected":known_rejected,
        "fixed_known_mask_sha256":digest(known_mask),"known_pixels":int(known_mask.sum()),
        "remaining_pixels":int((~known_mask).sum()),
        "known_region_changed_output_lanes":int(np.count_nonzero(known_out1[known_mask]!=known_out2[known_mask])),
        "outside_known_region_difference":differences(known_out2,known_out1,~known_mask),
        "distinguishing_yxc":np.argwhere((known_out1!=known_out2)&(~known_mask[...,None]))[:16].tolist(),
        "scope":"Compatible with rounded full colour tensor plus verified unwarped foliage overlap. Aligned glass RGB is not assumed invertible or silently used as raw values."}
    # Direct sampler comparison leaves all other arithmetic and stores unchanged.
    sampler_only={"ideal64_vs_frozen":results["ideal_sampler64"]["changed_validity_count"],
                  "observed8_vs_frozen":results["observed_fraction8"]["changed_validity_count"],
                  "rne_vs_frozen":results["rne_stores_source32"]["changed_validity_count"]}
    arrays={f"{name}_{key}":value for name,state in states.items() for key,value in state.items()
            if key in ("validity","sampled_history")}
    return {"scope":"CPU intervention on rejected C8 fixture; this is not production B4 or actual GPU execution",
        "expected_array_authority":"Frozen CPU outputs except older pre-UAV soft2 expected; actual GPU comparison exists only as aggregate historical JSON",
        "fixed_population":{"history_cells":4096,"rgb_output_elements":786432,
            "mask":"all published cells/pixels; no candidate-dependent selection"},
        "profiles":results,"decision_interventions":sampler_only,"missing_bits_witness":witness,
        "verified_overlap_recovery":overlap,
        "historical_gpu_gate_count":9,"historical_gpu_gate_map_available":False},arrays


def anchor_calibration():
    from numerical_contract.fixedpoint import frame_sum_bounds
    from numerical_contract.anchor_gain import replay_calibration
    reference=module_from_file("_contract_anchor",ANCHOR/"anchor_reference.py")
    rows=[]; aggregate={"combined":[],"native_policy":[]}
    for group in aggregate:
        for path in sorted((ANCHOR/"fixtures"/group).glob("*.npz")):
            with np.load(path,allow_pickle=False) as f:
                for j,frame in enumerate(f["frames"]):
                    stats,recalled=f["stats"][j],f["recalled"][j]
                    mask=f["fixed_mask"][j]
                    np.testing.assert_array_equal(reference.fixed_measurement_mask(stats,recalled),mask)
                    estimate=float(f["frame_ratio"][j]); age=int(f["k"][j])
                    gain=reference.predict(stats,recalled,age,estimate,
                                           policy="native" if group=="native_policy" else "combined")
                    error=(gain.astype(np.float64)-f["gain"][j].astype(np.float64)).ravel()
                    aggregate[group].append(error)
                    row={"group":group,"capture":path.stem,"frame":int(frame),
                         "k":age,"grid_shape":list(mask.shape),"fixed_mask_count":int(mask.sum()),
                         "fixed_mask_sha256":digest(mask),"gain_vs_stored_gpu":differences(gain,f["gain"][j]),
                         "frame_ratio_authority":"exported exact combined uint32 atomics" if group=="combined" else "stored-half estimate; original native uint64 atomics absent"}
                    if group=="native_policy":
                        row["bounds"]={}
                        for rounding in ("rne","rtz"):
                            bounds=frame_sum_bounds(stats[...,0],recalled[...,0],mask,rounding=rounding)
                            row["bounds"][rounding]=bounds.as_dict()
                    rows.append(row)
    summary={g:{"frames":sum(r["group"]==g for r in rows),
                **differences(np.concatenate(errors),np.zeros(sum(len(e) for e in errors)))}
             for g,errors in aggregate.items()}
    return {"scope":"CPU Gain reference versus recorded GPU grid fields; no recall reconstruction, no new GPU/RR execution",
            "summary":summary,"frames":rows,
            "gain_store_intervention":replay_calibration(ANCHOR)}


def encoding_calibration():
    """One fixed analytic octahedral population, never a captured image score."""
    from numerical_contract.encoding import (pack_normal11, unpack_normal11,
        pack_normal16_old, unpack_normal16_old, octahedral_decode, angular_error_degrees)
    codes=np.arange(65536,dtype=np.float32)
    uv=np.stack((np.floor(codes/256),codes%256),-1)/np.float32(255)
    original=octahedral_decode(uv)
    rows=[]
    for encoding,pack,unpack in (("audited_11bit",pack_normal11,unpack_normal11),
                               ("old_normalized_16bit",pack_normal16_old,unpack_normal16_old)):
        for rounding in ("rne","rtz"):
            encoded=pack(uv)
            stored=store_fp16(encoded,rounding=rounding)
            restored=unpack(stored)
            decoded=octahedral_decode(restored)
            angle=angular_error_degrees(original,decoded)
            # A self-surface gate starts true for every input. Keep the same
            # float32 dot staging and threshold on the same fixed population.
            dot=np.sum(original*decoded,axis=-1,dtype=np.float32)
            before=np.sum(original*original,axis=-1,dtype=np.float32)>np.float32(.9)
            after=dot>np.float32(.9)
            restored_code=(np.floor(stored*np.float32(65535)+np.float32(.5))
                           if encoding=="old_normalized_16bit" else pack(restored))
            intended=codes if encoding=="old_normalized_16bit" else encoded
            rows.append({"encoding":encoding,"rounding":rounding,"population":len(codes),
                "lost_payload_count":int(np.count_nonzero(restored_code!=intended)),
                "angular_error_degrees":{"p50":float(np.percentile(angle,50)),
                    "p90":float(np.percentile(angle,90)),"p99":float(np.percentile(angle,99)),
                    "max":float(angle.max())},
                "guide_threshold":.9,"changed_self_surface_decisions":int(np.count_nonzero(before!=after))})
    return {"scope":"analytic CPU guide distortion, not image-quality or captured GPU output",
        "decision_scope":"one-sided synthetic guide perturbation: original decoded normal versus stored/redecoded normal, not production SurfaceWeight with both center and tap guides encoded",
        "population_recipe":"all (qx/255,qy/255), qx,qy=0..255, original decoded using source-shaped octahedral_decode",
        "uv_sha256":digest(uv),"normal_sha256":digest(original),"comparisons":rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=HERE/"evidence")
    parser.add_argument("--colour-only",action="store_true")
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    colour,arrays=colour_calibration()
    result={"schema":"fsrd.numerical-calibration.v1","contract_version":__version__,
            "executor":"fresh Linux CPU/NumPy","gpu_executed":False,"colour":colour}
    if not args.colour_only:
        result["anchor"]=anchor_calibration()
        result["encoding"]=encoding_calibration()
    (args.output/"calibration.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    np.savez_compressed(args.output/"calibration_intermediates.npz",**arrays)
    print(json.dumps({"colour_decisions":colour["decision_interventions"],
                      "nonidentifiability_witness":colour["missing_bits_witness"],
                      "anchor":result.get("anchor",{}).get("summary"),
                      "gain_store_intervention":result.get("anchor",{}).get("gain_store_intervention",{}).get("summary"),
                      "encoding":result.get("encoding")},indent=2,allow_nan=False))


if __name__=="__main__":main()
