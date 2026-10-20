# Independent known-bad reproduction

Executed by the skeptical reviewer before reading candidate results or claimed
wins. This is a CPU reproduction; historical GPU receipts are not new GPU runs.

## Frozen soft2 halo regression

From `research/astra20261020/portable/colour`:

```sh
python -B compare.py --quality-gate
```

Observed exit code: **1**, as expected for the known rejected candidate. The
frozen CPU comparison reports `rejected_halo_regression`, with **6 of 32**
synthetic edge/phase cases worse than B4. At normal-edge phase 4, mean right-side
bleed is `0.057179879397153854` for B4 and `0.0982605442404747` for soft2; at
depth-edge phase 4 it is `0.057179879397153854` and `0.0977054163813591`.
Those are newly executed CPU model numbers, not the separately stored GPU
values. Full output and exact execution record are retained alongside this file.
The expected rejection is a successful falsifier; it is not an accepted fix.

## Coordinate and brightness controls

From repository root:

```sh
python -B research/astra20261020/candidates/06-moving-bottle/review/reproduce_secondary_controls.py
```

The immutable packaged coordinate helper gives exactly zero position error for
a moving crop whose origin shift cancels physical backward motion. Deliberate
wrong-sign, omitted-crop and ROI-for-render-scale controls respectively incur
`17.88854381999832`, `8.94427190999916`, and `8.856942732699162` pixels of error.
The 48 supported pixels preserve the analytic ramp and the 15 border pixels
remain NaN (unknown), rather than acquiring clamped history.

The unchanged 4-pixel-lagged stripe at half brightness has exactly half its tail
energy while retaining the same centroid and support at the fixed 0.2 threshold.
An overly high 0.6 threshold makes its support disappear. Neither observation
repairs its unchanged 4-pixel geometric lag. This control guards against calling
darkening or vacuous empty support a shape improvement.

The review plan was frozen in `REVIEW_PLAN.md` before candidate result inspection.
