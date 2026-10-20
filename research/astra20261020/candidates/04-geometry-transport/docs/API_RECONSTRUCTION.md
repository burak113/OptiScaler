# Reconstruction interface for jobs02/03/06/07/08

Import `reconstruction.py` by adding this candidate directory to Python's module
path. It needs NumPy only. The module does not import production, Windows, GPU
or another job's uncommitted files. See also `API_TRANSPORT.md` in this directory.

## Input contracts

| Type | Fields and conventions |
| --- | --- |
| `GeometryField` | `position[H,W,3]`, `normal[H,W,3]`, Boolean `observed[H,W]`, Boolean `eligible[H,W]`, optional `depth[H,W]`. Positions and normals share one declared world/view basis. Depth is original signed linear view depth, not device Z or a corrected guide. If omitted, position.z is treated as view depth. |
| `Policy` | Integral cell size; finite absolute/relative plane tolerance, normal cosine and minimum interpolation weight. Defaults C8, 1e-5, 1e-4, cos3deg, 1e-8. These constants were frozen before held-out sweeps. |
| `CellSupport` | Per-cell plane point, unit normal, positive depth scale, observable validity, observed/eligible fractions, active extent and policy. Cell count is ceil(active/cell); incomplete edge cells remain invalid. |
| `EstimatorSupport` | Cell geometry **plus** validity of the actual gain footprint and donor count. A current-cell certificate alone cannot approve a gain from other cells or uncertain recalled keys. |
| `Reconstruction` | Full-resolution gain, original accepted interpolation mass, contributing-tap count, query eligibility. Output gain=1 when disabled/unknown/unsupported. Partial mass is not a temporal-history publication certificate. |

All arrays are indexed `[y,x]`; extents are `(width,height)`. Texel centres are
`(x+.5,y+.5)`. Gain interpolation uses physical coarse centres `C*(cell+.5)`;
it does not stretch a floor-sized grid across an odd render extent. Array
allocation can be larger than active data, but callers must slice/describe the
active `GeometryField` explicitly. A crop origin belongs in the transport API;
the reconstruction field has already been expressed in one common point basis.

## Producer obligations and functions

1. `certify_cells(field, policy)` checks every current pixel of each complete
   cell for observation/eligibility, finite nonzero depth, valid normal, normal
   compatibility and plane residual. Four corners or a centre cannot establish
   this full-cell certificate. The tolerance establishes observable geometric
   compatibility only; it cannot establish hidden physical surface identity.
2. `local_estimator_support(cells, donor_valid)` applies only to a gain measured
   from this exact certified footprint and valid recalled support. `donor_valid`
   must be Boolean. NaN/numeric masks are rejected instead of becoming true.
3. `certify_estimator_support(cells, donor_weights, donor_valid, offsets)` checks
   every actual nonzero donor. Native baseline offsets are the Cartesian product
   of `(-3,0,3)` in cells; repeated clamped estimator taps are represented exactly.
   The caller supplies weights and key-validity provenance from the original
   measurement. Incompatible/unknown donors invalidate the entire mixed target;
   the function does not repair it by pretending they had zero weight.
4. `reconstruct(gain, support, query, method="supported")` rejects foreign or
   unknown interpolation taps and normalizes surviving weights. Both the query's
   own eligibility and each estimator certificate are mandatory. `method="hard"`
   requires the whole positive-weight stencil; missing support produces identity.
   Neither method uses colour or hit distance as a surrogate geometry guide.
5. `apply_rgba` applies the scalar gain in the CPU model while preserving alpha
   bits and exact identity. This is not proof of typed-UAV GPU bit equivalence.

Normal validity, observation support and static/history eligibility are separate
roles. Sky/zero depth, invalid normal, missing observation and unproved history
produce identity. Missing reflection distance disables **virtual** transport in
the transport API; it does not silently substitute a surface point as equivalent.
Colour can describe signal level but must not rewrite correspondence guides.

## Exact-gain versus exact-support experiments

The primary phase sweep gives the coarse grid analytic **point-centre** gains.
For an open one-pixel strip centred between texels, the continuous centre can
land on foreground even when every observed texel centre is background. A point
gain is then not an exact statistic of the certified discrete cell. The first
combined oracle comparison exposed a maximum 0.2 mismatch; its failed receipt
is preserved in `evidence/experiments_before_oracle_separation.json` (relative
to the candidate root), together with `evidence/oracle_discrepancy.json`.

The final sweep retains that primary experiment and reports its disagreement
cell/scenario counts. A separate exact-footprint intervention sets gain .8 only
on **independently oracle-pure** observed static cells. Expected output is .8
where immutable query eligibility and independent support overlap, identity
elsewhere. This separates estimator/representation error from reconstruction.
No candidate thresholds were tuned and no failure was relabelled as a success.

## Boundaries on reuse

An exact synthetic label is evaluation truth, never a production material input.
Coplanar material/light changes and depth layers below guide precision or plane
tolerance can be indistinguishable. A certificate supplied with false provenance
can make the output wrong: the retained tests demonstrate this explicitly.
Use this interface to communicate supported measurements; do not claim its
conditional analytic zero-leakage result is a measured native RR improvement.
