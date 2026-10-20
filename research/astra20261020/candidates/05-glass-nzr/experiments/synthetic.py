"""Preregistered analytic stage-surrogate discriminator; NEVER native RR replay.

Commands (repository root):
  python -B research/astra20261020/candidates/05-glass-nzr/experiments/synthetic.py --split development
  python -B research/astra20261020/candidates/05-glass-nzr/experiments/synthetic.py --split holdout

All sequences are chronological/unlooped. Truth is available ONLY to metrics.
The candidate receives external analytic noise/support sidecars, not truth RGB.
The sidecar is not available in the handoff's glass fixture. Five noise models
separate valid independent-noise behavior from temporal/spatial assumptions.
"""

from pathlib import Path
import argparse
import hashlib
import json
import shlex
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from glass_candidate import CandidateConfig, SupportUncertainty, shrink_specular

DEVELOPMENT_SEEDS = tuple(range(1000, 1016))
HOLDOUT_SEEDS = tuple(range(2000, 2048))
FRAMES, HEIGHT, WIDTH = 32, 40, 56
NOISE_MODELS = ("independent_gaussian", "sparse_heavy_tail", "temporal_ar1",
                "spatial_correlated_honest", "spatial_correlated_false_contract")
LUMA = np.array([.2126, .7152, .0722], np.float32)
CONFIG = CandidateConfig(enabled=True, noise_scale=1., min_effective_count=8.)


def blur3(image):
    """Unit-sum binomial blur, spatial axes -3/-2 for either F/H/W/C or H/W/C."""
    result = image.astype(np.float32, copy=False)
    for axis in (-3, -2):
        pads = [(0, 0)] * result.ndim
        pads[axis] = (1, 1)
        padded = np.pad(result, pads, mode="edge")
        indices = [slice(None)] * result.ndim
        terms = []
        for offset in range(3):
            indices[axis] = slice(offset, offset + result.shape[axis])
            terms.append(padded[tuple(indices)])
        result = np.float32(.25) * (terms[0] + np.float32(2) * terms[1] + terms[2])
    return result


def hash_array(array):
    a = np.asarray(array)
    hasher = hashlib.sha256()
    hasher.update(str(a.dtype).encode())
    hasher.update(json.dumps(a.shape).encode())
    hasher.update(a.tobytes(order="C"))
    return hasher.hexdigest()


def _glyphs():
    glyphs = ("10001/11001/10101/10011/10001/10001/10001",
              "11111/00001/00010/00100/01000/10000/11111",
              "11110/10001/10001/11110/10100/10010/10001")
    text = np.zeros((HEIGHT, WIDTH), bool)
    for index, glyph in enumerate(glyphs):
        for y, row in enumerate(glyph.split("/")):
            for x, value in enumerate(row):
                text[4+y, 4+index*7+x] = value == "1"
    return text


def effective_ar_count(count, rho):
    n = int(count)
    k = np.arange(1, n, dtype=np.float64)
    return float(n / (1 + 2 * np.sum((1-k/n) * rho**k)))


def make_sequence(seed, model):
    """Return generated analytic observations, masks and supplied sidecars.

    raw surrogate = spatially softened current truth + shared mild noise.
    selected surrogate = sharp current truth + same mild noise + extra noise.
    Thus correction noise = extra noise, with known variance/covariance. No
    provider, robust reference fit, selector or reflection history is modeled.
    """
    model_index = NOISE_MODELS.index(model)
    rng = np.random.default_rng(np.random.SeedSequence([int(seed), model_index]))
    yy, xx = np.mgrid[:HEIGHT, :WIDTH]
    text = _glyphs()
    base = np.empty((HEIGHT, WIDTH, 3), np.float32)
    base[...] = np.array([.16, .18, .22], np.float32)
    base += (.001 * xx + .0005 * yy)[..., None].astype(np.float32)
    base[text] += np.array([.28, .12, .05], np.float32)
    base[3:20, 31] += np.array([.04, .18, .3], np.float32)  # one-pixel line
    base[27:38, 2:16] = np.array([.014, .016, .021], np.float32)
    base[30:35, 7] += np.array([.015, .018, .008], np.float32)
    base[31, 35] += np.float32(.08)  # deliberately subnoise isolated detail
    base[34, 38] += np.array([.35, .18, .07], np.float32)
    # Opaque boundary has independent high-frequency structure.
    base[:, 44:] += (((xx[:,44:] + yy[:,44:]) % 2) * .12)[..., None]
    truth = np.repeat(base[None], FRAMES, axis=0)
    feature_centres = []
    for t in range(FRAMES):
        centre = 19.2 + .47*t + (4.5 if t >= 16 else 0.)
        feature_centres.append(centre)
        reflected = np.exp(-.5*((xx-centre)/.48)**2 - .5*((yy-23.5)/1.1)**2)
        truth[t] += reflected[..., None].astype(np.float32) * np.array([.42, .31, .16], np.float32)
        if t >= 12:
            truth[t] *= np.float32(1.25)
        if t >= 18:
            truth[t] *= np.array([1.12, .90, 1.08], np.float32)
    eligible = np.repeat(((xx < 44) & (yy >= 2) & (yy < 38))[None], FRAMES, axis=0)
    eligible[:10, :, 40:44] = False  # a newly visible support band
    surface = np.zeros((FRAMES, HEIGHT, WIDTH), np.int32)
    surface[:, (yy >= 21) & (xx >= 23)] = 1
    surface[~eligible] = -1
    # These masks are constructed from BASE setup before candidate evaluation.
    masks = {
        "evaluation": eligible.copy(),
        "grain": eligible & ((xx >= 34) & (xx <= 39) & (yy >= 3) & (yy <= 18))[None],
        "texture": eligible & ((xx >= 3) & (xx <= 24) & (yy >= 3) & (yy <= 12))[None],
        "stroke": np.broadcast_to(text, eligible.shape).copy(),
        "text_background": np.broadcast_to((~text) & (xx >= 3) & (xx <= 24) &
                                            (yy >= 3) & (yy <= 12), eligible.shape).copy(),
        "edge": eligible & (((np.abs(xx-23) <= 1) & (yy >= 21)) |
                             (np.abs(xx-44) <= 1))[None],
        "lowlight": eligible & ((xx >= 3) & (xx <= 14) & (yy >= 28) & (yy <= 36))[None],
        "response": eligible & ((xx >= 34) & (xx <= 39) & (yy >= 3) & (yy <= 18))[None],
    }
    noise_scale_map = np.ones((HEIGHT, WIDTH), np.float32)
    noise_scale_map[27:38, 2:16] = np.float32(.075)
    shared_sigma = np.float32(.003) * noise_scale_map
    selected_sigma = np.float32(.023) * noise_scale_map
    shared = rng.normal(size=truth.shape).astype(np.float32) * shared_sigma[None,...,None]
    if model == "sparse_heavy_tail":
        probability = np.float32(.04)
        amplitude = np.float32(.013) * noise_scale_map
        sparse = (rng.random(truth.shape) < probability).astype(np.float32)
        extra = amplitude[None,...,None] * (sparse/probability - np.float32(1))
        variance_channel = amplitude**2 * (np.float32(1)/probability - np.float32(1))
    elif model == "temporal_ar1":
        rho = np.float32(.85)
        extra = np.empty_like(truth)
        extra[0] = rng.normal(size=truth.shape[1:]).astype(np.float32) * selected_sigma[...,None]
        for t in range(1, FRAMES):
            innovation = rng.normal(size=truth.shape[1:]).astype(np.float32) * selected_sigma[...,None]
            extra[t] = rho*extra[t-1] + np.sqrt(np.float32(1)-rho*rho)*innovation
        variance_channel = selected_sigma**2
    elif model.startswith("spatial_correlated"):
        # A random vertical 2px stroke is indistinguishable from line detail at
        # this support. Equal per-pixel marginal variance is NOT coefficient
        # variance: correlated signs add in one Haar band rather than cancel.
        block_noise = rng.normal(size=(FRAMES, HEIGHT//2, WIDTH//2, 3)).astype(np.float32)
        extra = np.repeat(np.repeat(block_noise, 2, axis=1), 2, axis=2)
        extra *= np.where((xx % 2) == 0, 1., -1.).astype(np.float32)[None,...,None]
        extra *= selected_sigma[None,...,None]
        variance_channel = selected_sigma**2
    else:
        extra = rng.normal(size=truth.shape).astype(np.float32) * selected_sigma[None,...,None]
        variance_channel = selected_sigma**2
    raw = blur3(blur3(truth)) + shared
    selected = truth + shared + extra
    # No clipping is used to make a clean score. A rare out-of-range synthetic
    # observation is marked unsupported by the candidate's existing contract.
    selected[~eligible] = raw[~eligible]
    counts = np.full((FRAMES, HEIGHT, WIDTH), 64., np.float32)
    for t in range(7):
        counts[t] = t+1
    for t in range(20, 27):
        counts[t] = t-19
    if model == "temporal_ar1":
        for count in np.unique(counts):
            counts[counts == count] = effective_ar_count(count, .85)
    independent = np.ones((FRAMES, HEIGHT, WIDTH), bool)
    if model == "spatial_correlated_honest":
        independent[:] = False
    trace = np.broadcast_to(np.float32(3)*variance_channel, counts.shape).copy()
    masks["actual_nzr_changed"] = eligible & np.any(raw.view(np.uint32) != selected.view(np.uint32),axis=3)
    return {
        "truth": truth, "raw": raw, "selected": selected, "eligible": eligible,
        "surface": surface, "noise_trace": trace, "count": counts,
        "independent_spatial": independent, "masks": masks,
        "feature_centres": feature_centres,
        "negative_observation_words": int(np.count_nonzero(raw < 0)+np.count_nonzero(selected < 0)),
        "sidecar_scope": "analytic conditional noise injection; no captured/native uncertainty is claimed",
    }


def texture_gain(output, truth, mask):
    high_truth = truth-blur3(truth)
    high_output = output-blur3(output)
    target = high_truth[mask].astype(np.float64)
    observed = high_output[mask].astype(np.float64)
    return float(np.sum(target*observed)/max(np.sum(target*target),1e-30))


def metrics(output, sequence):
    truth, masks = sequence["truth"], sequence["masks"]
    error = output-truth
    luma_error = error @ LUMA
    high_error = (error-blur3(error)) @ LUMA
    active, quiet = masks["evaluation"], masks["grain"]
    pair_mask = active[1:] & active[:-1]
    temporal_error = np.diff(luma_error,axis=0)
    luma_output, luma_truth = output@LUMA, truth@LUMA
    def rms(x):
        x=np.asarray(x,dtype=np.float64)
        return float(np.sqrt(np.mean(x*x)))
    def contrast(field):
        return float(np.mean(field[masks["stroke"]])-np.mean(field[masks["text_background"]]))
    glint_ys, glint_xs = 31, 35
    neighbours = np.ones((3,3),bool); neighbours[1,1]=False
    out_near=luma_output[:,glint_ys-1:glint_ys+2,glint_xs-1:glint_xs+2]
    truth_near=luma_truth[:,glint_ys-1:glint_ys+2,glint_xs-1:glint_xs+2]
    glint_output=np.mean(luma_output[:,glint_ys,glint_xs]-out_near[:,neighbours].mean(axis=1))
    glint_truth=np.mean(luma_truth[:,glint_ys,glint_xs]-truth_near[:,neighbours].mean(axis=1))
    def response(frame):
        mask=masks["response"][frame] & masks["response"][frame-1]
        dy=np.mean((truth[frame]-truth[frame-1])[mask],axis=0,dtype=np.float64)
        dx=np.mean((output[frame]-output[frame-1])[mask],axis=0,dtype=np.float64)
        return float(np.dot(dx,dy)/max(np.dot(dy,dy),1e-30))
    moving_mask=np.zeros(active.shape,bool)
    for t,centre in enumerate(sequence["feature_centres"]):
        x=np.arange(WIDTH)[None,:]
        y=np.arange(HEIGHT)[:,None]
        moving_mask[t]=(np.abs(x-centre)<2.) & (np.abs(y-23.5)<2.)
    result={
        "rgb_rmse": rms(error[active]),
        "grain_highpass_error_rms": rms(high_error[quiet]),
        "positive_sparkle_error_p995": float(np.quantile(np.maximum(high_error[quiet],0),.995)),
        "absolute_sparkle_error_p995": float(np.quantile(np.abs(high_error[quiet]),.995)),
        "all_active_positive_highpass_error_p995": float(np.quantile(np.maximum(high_error[active],0),.995)),
        "all_active_absolute_highpass_error_p995": float(np.quantile(np.abs(high_error[active]),.995)),
        "temporal_error_rms": rms(temporal_error[pair_mask]),
        "output_temporal_rms_including_true_changes": rms(np.diff(luma_output,axis=0)[pair_mask]),
        "texture_contrast_gain": texture_gain(output,truth,masks["texture"]),
        "text_stroke_contrast_gain": contrast(luma_output)/max(contrast(luma_truth),1e-30),
        "isolated_glint_peak_gain": float(glint_output/max(glint_truth,1e-30)),
        "edge_rgb_rmse": rms(error[masks["edge"]]),
        "lowlight_rgb_rmse": rms(error[masks["lowlight"]]),
        "moving_reflection_rgb_rmse": rms(error[moving_mask & active]),
        "mean_luma_error": float(np.mean(luma_error[active],dtype=np.float64)),
        "light_step_immediate_gain": response(12),
        "colour_step_immediate_gain": response(18),
    }
    assert all(np.isfinite(value) for value in result.values()),result
    return result


def evaluate(seed, model):
    sequence=make_sequence(seed,model)
    raw,selected=sequence["raw"],sequence["selected"]
    candidate=np.empty_like(selected)
    accepted=changed=range_abstain=0
    for t in range(FRAMES):
        evidence=SupportUncertainty(sequence["noise_trace"][t],sequence["count"][t],
                                    np.ones((HEIGHT,WIDTH),bool),sequence["independent_spatial"][t],
                                    sequence["surface"][t])
        candidate[t],diagnostics=shrink_specular(raw[t],selected[t],sequence["eligible"][t],evidence,CONFIG)
        accepted+=diagnostics["accepted_blocks"]
        changed+=diagnostics["changed_pixels"]
        range_abstain+=diagnostics["range_abstain_blocks"]
    blend=raw+np.float32(.5)*(selected-raw)
    candidate_blend=raw+np.float32(.5)*(candidate-raw)
    # All controls have identical truth, frame order, masks and fixed support.
    variants={
        "raw_rr_surrogate": raw,
        "nzr_selected_surrogate": selected,
        "blend05": blend,
        "blend025_reduce_strength": raw+np.float32(.25)*(selected-raw),
        "candidate_nzr_diagnostic": candidate,
        "candidate_blend05": candidate_blend,
        "blur_blend05_null": blur3(blend),
        "freeze_blend05_null": np.repeat(blend[:1],FRAMES,axis=0),
    }
    gain_raw=texture_gain(raw,sequence["truth"],sequence["masks"]["texture"])
    gain_selected=texture_gain(selected,sequence["truth"],sequence["masks"]["texture"])
    gain_candidate=texture_gain(candidate_blend,sequence["truth"],sequence["masks"]["texture"])
    # Analytic-truth ORACLE comparator: select the scalar control with the same
    # texture regression coefficient. This changes no candidate setting.
    matched_strength=float(np.clip((gain_candidate-gain_raw)/max(gain_selected-gain_raw,1e-12),0,1))
    variants["detail_matched_scalar_null"]=raw+np.float32(matched_strength)*(selected-raw)
    output_metrics={name:metrics(output,sequence) for name,output in variants.items()}
    untouched=~sequence["eligible"]
    exact_untouched=int(np.count_nonzero(candidate[untouched].view(np.uint32)!=selected[untouched].view(np.uint32)))
    assert exact_untouched==0
    mask_hashes={key:hash_array(value) for key,value in sequence["masks"].items()}
    result={
        "seed":seed,"model":model,"frames":FRAMES,"height":HEIGHT,"width":WIDTH,
        "rng":"numpy.random.default_rng(SeedSequence([seed, model_index]))",
        "mask_hashes":mask_hashes,
        "mask_denominators":{key:int(np.count_nonzero(value)) for key,value in sequence["masks"].items()},
        "input_hashes":{key:hash_array(sequence[key]) for key in ("truth","raw","selected","noise_trace","count")},
        "metrics":output_metrics,"detail_matched_scalar_strength":matched_strength,
        "candidate_support":{"accepted_blocks":accepted,"changed_pixels":changed,
                             "range_abstain_blocks":range_abstain,
                             "protected_specular_differing_words":exact_untouched},
        "negative_observation_words":sequence["negative_observation_words"],
    }
    return result


def summarize(rows):
    summary={}
    for model in NOISE_MODELS:
        model_rows=[row for row in rows if row["model"]==model]
        if not model_rows:
            continue
        variants={}
        for name in model_rows[0]["metrics"]:
            measures={}
            for metric in model_rows[0]["metrics"][name]:
                values=np.array([row["metrics"][name][metric] for row in model_rows],np.float64)
                measures[metric]={"mean":float(np.mean(values)),"p10":float(np.quantile(values,.1)),
                                  "p90":float(np.quantile(values,.9)),"min":float(np.min(values)),
                                  "max":float(np.max(values))}
            variants[name]=measures
        paired={}
        for control in ("blend05","detail_matched_scalar_null"):
            metrics_compared={}
            for key in ("grain_highpass_error_rms","positive_sparkle_error_p995","temporal_error_rms",
                        "texture_contrast_gain","text_stroke_contrast_gain","isolated_glint_peak_gain"):
                ratios=np.array([row["metrics"]["candidate_blend05"][key]/row["metrics"][control][key]
                                 for row in model_rows],np.float64)
                metrics_compared[key]={"mean_ratio":float(np.mean(ratios)),
                                        "p10_ratio":float(np.quantile(ratios,.1)),
                                        "p90_ratio":float(np.quantile(ratios,.9)),
                                        "fraction_ratio_below_one":float(np.mean(ratios<1.))}
            paired[control]=metrics_compared
        summary[model]={"independent_seed_count":len(model_rows),"variants":variants,"paired_ratios":paired,
                        "mean_detail_matched_scalar_strength":float(np.mean([r["detail_matched_scalar_strength"] for r in model_rows])),
                        "total_negative_observation_words":sum(r["negative_observation_words"] for r in model_rows),
                        "total_accepted_blocks":sum(r["candidate_support"]["accepted_blocks"] for r in model_rows)}
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split",choices=("development","holdout"),required=True)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--executor",default="cloud Linux CPU caller (identity unspecified)")
    args=parser.parse_args()
    seeds=DEVELOPMENT_SEEDS if args.split=="development" else HOLDOUT_SEEDS
    output=(args.output or ROOT/"evidence"/f"synthetic_{args.split}.json").resolve()
    command_argv=["python","-B","research/astra20261020/candidates/05-glass-nzr/experiments/synthetic.py",*sys.argv[1:]]
    start=time.perf_counter()
    rows=[]
    for model in NOISE_MODELS:
        model_start=time.perf_counter()
        rows.extend(evaluate(seed,model) for seed in seeds)
        print(f"{args.split}: {model}, {len(seeds)} independent sequences, {time.perf_counter()-model_start:.3f}s",flush=True)
    result={
        "schema":"glass-nzr-analytic-stage-surrogate-results-v2",
        "executor":args.executor,
        "gpu_executed":False,"native_rr_executed":False,"game_observed":False,
        "split":args.split,"seeds":list(seeds),"noise_models":list(NOISE_MODELS),
        "frames_per_sequence":FRAMES,"shape_hwc":[HEIGHT,WIDTH,3],
        "candidate_config":{"noise_scale":1.,"min_effective_count":8.},
        "commands":[shlex.join(command_argv)],"command_argv":command_argv,
        "exit_code":0,"elapsed_seconds":time.perf_counter()-start,
        "source_sha256":{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (Path(__file__),ROOT/"src/glass_candidate.py")},
        "summary":summarize(rows),"per_sequence":rows,
        "interpretation_limits":[
            "Raw RR and NZR arrays are analytic current-frame surrogates, not native algorithm outputs.",
            "Variance/support are supplied analytic sidecars, not identifiable from the glass fixture.",
            "All model variants use the same frozen BASE masks/denominators and chronology.",
            "Temporal error subtracts true motion/light changes; output temporal RMS does not.",
            "Sparkle tails use the immutable quiet-flat grain mask; all-active high-pass error tails also include texture blur.",
            "Initial development results used all-active tails under a broad sparkle name; scope was corrected before holdout without candidate tuning.",
            "Detail-matched scalar control uses truth for evaluation only; candidate has no truth access.",
            "Spatial-correlated-false-contract is an intentional lie about the independence sidecar.",
            "No CPU timings estimate GPU milliseconds or resident VRAM."
        ],
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    display_output=str(output.relative_to(ROOT)) if output.is_relative_to(ROOT) else output.name
    print(json.dumps({"output":display_output,"sequences":len(rows),
                      "elapsed_seconds":result["elapsed_seconds"],"exit_code":0}),flush=True)


if __name__=="__main__":
    main()
