"""Render the stored low-contrast counterexample without re-running a model."""
from pathlib import Path
import os
import tempfile

import numpy as np

HERE = Path(__file__).resolve().parent


def main():
    with tempfile.TemporaryDirectory(prefix="native-colour-mpl-") as cache:
        os.environ.setdefault("MPLCONFIGDIR", cache)
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        with np.load(HERE / "low_contrast_arrays.npz", allow_pickle=False) as data:
            arrays = {k: data[k].copy() for k in data.files}
        fig, axes = plt.subplots(1, 4, figsize=(13, 3.3), constrained_layout=True)
        for ax, name in zip(axes[:3], ("truth", "raw", "log")):
            rgb = arrays[name][..., :3].astype(np.float32)
            ax.imshow(np.clip(rgb, 0, 1) ** (1 / 2.2), interpolation="nearest")
            ax.set_title(name)
            ax.axis("off")
        raw = arrays["raw"][..., :3].astype(np.float64)
        den = raw @ np.array([.2126, .7152, .0722])
        delta = np.abs(arrays["log"][..., :3].astype(np.float64) - raw).sum(-1) / den
        shown = np.where(arrays["unchanged_band"], delta, np.nan)
        im = axes[-1].imshow(shown, vmin=0, vmax=.07, cmap="magma", interpolation="nearest")
        axes[-1].set_title("Unchanged-right tint / BASE luma")
        axes[-1].axis("off")
        fig.colorbar(im, ax=axes[-1], shrink=.78)
        fig.suptitle("Same guides, low-contrast edge | 27 degrees, phase 4 | common exposure 1.0 / gamma 2.2")
        fig.savefig(HERE / "low_contrast_panels.png", dpi=140)
        plt.close(fig)


if __name__ == "__main__":
    main()
