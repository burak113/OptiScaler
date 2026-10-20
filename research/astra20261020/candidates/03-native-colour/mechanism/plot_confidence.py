"""Plot the saved untuned confidence probe; optional Matplotlib dependency."""
from pathlib import Path
import json
import os
import tempfile
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "native-colour-mpl"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
r = json.loads((HERE / "confidence_results.json").read_text())
summary = r["summary"]
x = np.arange(2)
labels = ["Moderate noise", "Sparse coloured tail"]
fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.2), constrained_layout=True)
axes[0].bar(x, [v["null_hf_ratio_median"] for v in summary], color=["#197a9c", "#bd4356"], width=.55)
axes[0].axhline(.8, color="black", linestyle="--", linewidth=1, label="Required: at most 0.8")
axes[0].axhline(1, color="grey", linewidth=.8)
axes[0].set_ylim(0, 1.12)
axes[0].set_ylabel("Probe / original chroma-HF p90")
axes[0].set_title("Null grain: lower is better")
axes[0].legend(fontsize=8)
axes[1].bar(x, [v["bias_dose_retention_median"] for v in summary], color=["#197a9c", "#bd4356"], width=.55)
axes[1].axhline(.9, color="black", linestyle="--", linewidth=1, label="Required: at least 0.9")
axes[1].set_ylim(0, 1.12)
axes[1].set_ylabel("Fraction of original useful correction")
axes[1].set_title("Persistent bias: retain correction")
axes[1].legend(fontsize=8)
axes[2].bar(x-.17, [v["original_change_dose_median"] for v in summary],
            width=.33, color="#697684", label="Original log")
axes[2].bar(x+.17, [v["probe_change_dose_median"] for v in summary],
            width=.33, color="#c76640", label="Variance confidence")
axes[2].axhspan(-.3, 0, color="#bd4356", alpha=.1)
axes[2].axhline(0, color="black", linewidth=1)
axes[2].set_ylim(-.3, 1.12)
axes[2].set_ylabel("Projected raw-to-truth correction dose")
axes[2].set_title("True change: negative means wrong direction")
axes[2].legend(fontsize=8)
for ax in axes:
    ax.set_xticks(x, labels, fontsize=9)
    ax.grid(axis="y", alpha=.15)
fig.suptitle("Untuned smooth variance confidence fails useful-correction gates\n"
             "Development seeds only; identical full-resolution support and RGB means", fontsize=13)
fig.savefig(HERE/"confidence_tradeoff.png", dpi=170)
print(json.dumps({"figure": "confidence_tradeoff.png", "matplotlib": matplotlib.__version__}))
