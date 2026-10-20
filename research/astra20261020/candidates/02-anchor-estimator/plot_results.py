"""Static scientific panels from saved measurements, with matched scales."""
import json
import os
from pathlib import Path
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "anchor02-matplotlib-cache"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
OUT = EVIDENCE / "figures"
COLORS = {"baseline": "#355c93", "provisional_diagnostic": "#d2782d", "causal_abstainer": "#247c61"}
NAMES = {"baseline": "Frozen native control", "provisional_diagnostic": "Provisional diagnostic", "causal_abstainer": "Causal abstention (identity)"}


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / (name + ".png"), dpi=150, bbox_inches="tight", facecolor="white",
                metadata={"Software": "Job02 Matplotlib CPU evidence"})
    plt.close(fig)


def fixed_fields():
    with np.load(EVIDENCE / "fixed_mask_fields.npz", allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files}
    captures = [c for c in ("22f9ca14", "87ee1fba", "2405579e") if c + "_stats" in arrays]
    fig, axes = plt.subplots(len(captures), 5, figsize=(15, 3.5 * len(captures)), constrained_layout=True,
                             squeeze=False)
    gainnorm, levelnorm = Normalize(.8, 1.), Normalize(-4., 0.)
    for row, cap in enumerate(captures):
        frame = int(arrays[cap + "_frames"][0])
        mask = arrays[cap + "_mask"][0]
        data = [mask.astype(float), np.log10(np.maximum(arrays[cap + "_stats"][0, ..., 0].astype(float), 1e-4)),
                arrays[cap + "_baseline_cpu"][0], arrays[cap + "_provisional_diagnostic"][0],
                arrays[cap + "_causal_abstainer"][0]]
        titles = ["Immutable BASE support", "Current physical luma (log10)", "Frozen native gain", "Provisional diagnostic gain", "Applied research gain: identity"]
        for col, (a, title) in enumerate(zip(data, titles)):
            ax = axes[row, col]
            cmap = "gray" if col == 0 else ("magma" if col == 1 else "viridis")
            norm = Normalize(0, 1) if col == 0 else (levelnorm if col == 1 else gainnorm)
            image = ax.imshow(a, cmap=cmap, norm=norm, interpolation="nearest", aspect="equal")
            ax.set_title(title, fontsize=10)
            ax.set_xlabel("original grid x"); ax.set_ylabel("original grid y")
            if col == 0:
                ax.set_ylabel(f"{cap} / frame {frame}\n{a.shape[1]} x {a.shape[0]} cells\noriginal grid y", fontsize=9)
            if col in (1, 4):
                fig.colorbar(image, ax=ax, fraction=.05, pad=.03)
    fig.suptitle("Native stored fields: fixed masks, original aspect, identical scales\n"
                 "Gain is a CPU input-correction field; these are not fresh RR or game images.", fontsize=13)
    save(fig, "native_fixed_fields")


def trajectories(captured):
    fig, axes = plt.subplots(2, 3, figsize=(15, 7), sharey=True, constrained_layout=True)
    names = {"baseline_cpu": "Frozen CPU control", "provisional_diagnostic": "Provisional diagnostic", "causal_abstainer": "Identity"}
    colors = dict(zip(names, COLORS.values()))
    for row, group in enumerate(("native_policy", "combined")):
        for col, cap in enumerate(("22f9ca14", "87ee1fba", "2405579e")):
            ax = axes[row, col]
            item = captured.get(group + "/" + cap)
            if not item:
                ax.set_visible(False); continue
            for name, label in names.items():
                values = item["metrics"][name]["trajectory"]
                frames = np.array([v["frame"] for v in values])
                ys = np.array([1 + v["energy_drift_fraction"] if v["energy_drift_fraction"] is not None else np.nan for v in values])
                # Gaps remain gaps; a sparse native witness is not a continuous replay.
                cuts = np.where(np.diff(frames) != 1)[0] + 1
                for i, ids in enumerate(np.split(np.arange(len(frames)), cuts)):
                    ax.plot(frames[ids], ys[ids], ".-", color=colors[name], markersize=4, linewidth=1.2,
                            label=label if i == 0 else None)
            ax.set_ylim(.78, 1.015)
            ax.set_xlabel("original chronological frame id")
            ax.set_ylabel("input-energy-weighted gain on BASE mask")
            scope = "native sparse snapshots" if row == 0 else "combined-domain stress only"
            ax.set_title(f"{cap} | {scope}", fontsize=10)
            ax.grid(alpha=.2)
            if col == 0:
                ax.legend(fontsize=8, loc="lower left")
    fig.suptitle("Chronological gain trajectories — identical gain scale; missing frames are not filled", fontsize=13)
    save(fig, "gain_trajectories")


def synthetic_panels(data):
    controls = data["null_and_support_controls"]
    kinds = ["stationary_independent", "spatial_correlated", "temporal_correlated", "heavy_tail_bursts", "equal_energy_antithetic"]
    labels = ["independent", "spatial blocks", "temporal AR(0.92)", "heavy tails", "antithetic"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)
    x = np.arange(len(kinds)); width = .34
    for offset, name in ((-.17, "baseline"), (.17, "provisional_diagnostic")):
        values = [100 * controls[k]["matched_excess_dose_strengths"][name]["correction_dose"]["mean"] for k in kinds]
        axes[0].bar(x + offset, values, width, color=COLORS[name], label=NAMES[name])
    axes[0].set_xticks(x, labels, rotation=18, ha="right")
    axes[0].set_ylabel("false-positive energy removal (%)")
    axes[0].set_title("No-excess nulls: lower is better")
    axes[0].grid(axis="y", alpha=.2)
    lights = [r for r in data["true_light_controls"] if r["kind"] == "light_during_motion" and r["step"] in (1.1, 1.25, 1.4)]
    x = np.arange(len(lights))
    for offset, name in ((-.24, "baseline"), (0., "provisional_diagnostic"), (.24, "causal_abstainer")):
        values = [r["matched_excess_dose_strengths"][name]["light_response"]["response_area_ratio"] for r in lights]
        axes[1].bar(x + offset, values, .24, label=NAMES[name], color=COLORS[name])
    axes[1].set_xticks(x, [str(r["step"]) + "x" for r in lights])
    axes[1].set_ylim(0, 1.1); axes[1].axhline(1, color="gray", linestyle="--", linewidth=1)
    axes[1].set_title("Genuine light step during motion: 1 preserves response")
    axes[1].set_ylabel("22-frame response area / true step area")
    axes[1].grid(axis="y", alpha=.2)
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=3, fontsize=9)
    target = data["dose_calibration"]["target_dose"] * 100
    fig.suptitle(f"Matched synthetic excess removal: {target:.5f}%\n"
                 "Provisional estimator still fails a correlated null and genuine light. Identity removes zero excess.", fontsize=12)
    save(fig, "matched_dose_tradeoffs")

    fig, axes = plt.subplots(1, 3, figsize=(14, 4), sharex=True, sharey=True, constrained_layout=True)
    for ax, row in zip(axes, lights):
        for name, color in COLORS.items():
            values = row["matched_excess_dose_strengths"][name]["light_response"]["per_frame_response_fraction"]
            ax.plot(np.arange(len(values)), values, color=color, label=NAMES[name], linewidth=1.7)
        ax.axhline(1, color="gray", linestyle="--", linewidth=1)
        ax.set_ylim(-.02, 1.06); ax.set_title(f"True {row['step']}x illumination")
        ax.set_xlabel("frames since light change"); ax.grid(alpha=.2)
    axes[0].set_ylabel("preserved fraction of genuine light step")
    axes[0].legend(fontsize=8, loc="center left")
    fig.suptitle("Analytic stale-reference control during motion — same timing and response scale\n"
                 "A known counterexample, not a prediction of missing six-key history or AMD RR output.", fontsize=12)
    save(fig, "light_response_trajectories")


def main():
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    captured = json.loads((EVIDENCE / "captured_results.json").read_text())
    synthetic = json.loads((EVIDENCE / "synthetic_results.json").read_text())
    fixed_fields(); trajectories(captured); synthetic_panels(synthetic)
    print(json.dumps({"matplotlib": matplotlib.__version__, "figures": [p.name for p in sorted(OUT.glob("*.png"))]}, indent=2))


if __name__ == "__main__":
    main()
