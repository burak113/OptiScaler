"""Optional Matplotlib scientific figures for experiment.py; no new experiments.

Requires Matplotlib (executed version 3.10.8). Core tests need only NumPy.
Run after experiment.py from any working directory.
"""
from pathlib import Path
import json
import os
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "native-colour-mpl"))
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["svg.hashsalt"] = "native-colour-mechanism-v1"
import matplotlib.pyplot as plt
import numpy as np

import experiment as e


def representation_figure(result):
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.5), constrained_layout=True)
    colours = {"arithmetic_before_transform": "#197a9c", "robust_per_sample_log": "#bd4356"}
    labels = {"arithmetic_before_transform": "Linear RGB mean before transform",
              "robust_per_sample_log": "Robust per-sample log (rejected general target)"}
    for ax, scenario, title in zip(axes,
            ["valid_coloured_radiance_tail", "biased_colour_contamination"],
            ["Rare colour carries valid radiance", "Rare colour is injected contamination"]):
        for method in colours:
            means, lows, highs = [], [], []
            for support in e.SUPPORTS:
                values = [r[method]["chroma_rmse_mean"] for r in result["finite_sample"]
                          if r["scenario"] == scenario and r["support"] == support
                          and r["lobe_scale_only"] == "diffuse"]
                means.append(np.mean(values)); lows.append(min(values)); highs.append(max(values))
            ax.plot(e.SUPPORTS, means, marker="o", linewidth=2, label=labels[method], color=colours[method])
            ax.fill_between(e.SUPPORTS, lows, highs, color=colours[method], alpha=.15)
        ax.set_xscale("log", base=2)
        ax.set_xticks(e.SUPPORTS, [str(x) for x in e.SUPPORTS])
        ax.set_ylim(-.015, .65)
        ax.set_xlabel("Independent observations per target")
        ax.set_ylabel("Normalized chroma RMSE (fixed true luminance)")
        ax.set_title(title)
        ax.grid(alpha=.18)
    axes[0].legend(loc="center right", fontsize=8)
    fig.suptitle("The observation model decides whether robust rejection is correct", fontsize=13)
    fig.savefig(e.HERE / "representation_tradeoff.png", dpi=170)
    fig.savefig(e.HERE / "representation_tradeoff.svg", metadata={"Date": None})
    plt.close(fig)


def mixed_scene(phase):
    width = 96
    pixel = np.arange(width)
    left_truth = e.colour(np.array([.65, .20, .10])) * .2
    right_truth = e.colour(np.array([.15, .38, .75])) * .2
    left_raw = left_truth * [1.18, .93, .87]
    left_raw *= .2 / e.luminance(left_raw)
    left = pixel < 44 + phase
    truth = np.where(left[:, None], left_truth, right_truth)
    raw = np.where(left[:, None], left_raw, right_truth)
    correct_gain = np.where(left[:, None],
                            np.clip(e.colour(left_truth)/e.colour(left_raw), .75, 1.33), 1.0)
    clean = e.restore(raw, correct_gain)
    coarse = correct_gain.reshape(-1, 4, 3).mean(axis=1)
    dirty_reconstruction = e.restore(raw, e._linear_interpolate_grid(coarse, width))
    mixed_target = truth.reshape(-1, 4, 3).mean(axis=1)
    dirty_target = e.ratio_apply(raw, mixed_target[pixel // 4])
    return raw, clean, dirty_reconstruction, dirty_target


def mixing_figure(result):
    stages = ("Raw RR", "Oracle clean target + reconstruction",
              "Clean target + dirty reconstruction", "Dirty target + oracle reconstruction")
    fig, axes = plt.subplots(4, 4, figsize=(13.0, 5.4), constrained_layout=True)
    for phase in range(4):
        arrays = mixed_scene(phase)
        for j, (ax, array) in enumerate(zip(axes[phase], arrays)):
            # Every panel uses the same synthetic crop, aspect, exposure and
            # transfer. This display is not game albedo remodulation.
            rgb = np.repeat(array[None], 24, axis=0)
            ax.imshow(np.clip(rgb, 0, 1) ** (1/2.2), interpolation="nearest", aspect="equal")
            ax.axvline(43.5+phase, color="white", linestyle=":", alpha=.55, linewidth=.8)
            ax.set_xticks([]); ax.set_yticks([])
            if phase == 0:
                ax.set_title(stages[j], fontsize=9)
            if j == 0:
                ax.set_ylabel(f"Phase {phase}", fontsize=10)
        baseline = arrays[0]
        band = (np.arange(96) >= 44+phase) & (np.arange(96) < 48+phase)
        for index, key in [(2, "clean_target_dirty_reconstruction_right_max"),
                           (3, "dirty_target_oracle_reconstruction_right_max")]:
            value = float(np.max(np.sum(np.abs(arrays[index]-baseline), axis=-1)[band] /
                                 e.luminance(baseline)[band]))
            assert abs(value-result["mixing_ablation"][phase][key]) < 1e-12
    fig.suptitle("Target information loss and reconstruction leakage are separate defects\n"
                 "Equal-luminance synthetic regions; common exposure 1, diagnostic gamma 1/2.2", fontsize=12)
    fig.savefig(e.HERE / "mixing_ablation_panels.png", dpi=190)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.5, 4.0), constrained_layout=True)
    phase = 2
    raw, clean, reconstruction, target = mixed_scene(phase)
    maximum_error = 0.0
    for array, label, colour in [(clean, "Oracle clean both", "#277950"),
                                (reconstruction, "Clean target; dirty reconstruction", "#197a9c"),
                                (target, "Dirty target; oracle reconstruction", "#bd4356")]:
        error = np.sum(np.abs(array-raw), axis=-1)/e.luminance(raw)
        maximum_error = max(maximum_error, float(error.max()))
        ax.plot(np.arange(96), error, label=label, color=colour, linewidth=2)
    ax.axvline(45.5, color="black", linestyle="--", alpha=.5)
    ax.axvspan(46, 49, color="#f4b940", alpha=.15, label="Immutable unchanged-side band")
    ax.set_xlim(36, 58); ax.set_ylim(0, maximum_error * 1.05)
    ax.set_xlabel("Full-resolution pixel x (phase 2)")
    ax.set_ylabel("RGB change / fixed raw luminance")
    ax.set_title("Left correction is intentional; every right-side change is contamination")
    ax.legend(fontsize=8)
    ax.grid(alpha=.15)
    fig.savefig(e.HERE / "mixing_ablation_profile.png", dpi=170)
    plt.close(fig)


def main():
    result = json.loads((e.HERE / "results.json").read_text())
    representation_figure(result)
    mixing_figure(result)
    print(json.dumps({"matplotlib": matplotlib.__version__, "figures": [
        "representation_tradeoff.png", "representation_tradeoff.svg",
        "mixing_ablation_panels.png", "mixing_ablation_profile.png"]}))


if __name__ == "__main__":
    main()
