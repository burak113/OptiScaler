# Retired experiment

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Floor RR Routing was removed at the user's request. This document records the
earlier experiment, not the current production controls or signal contract.

---

# Flat-region RR routing — opt-in production experiment

The default remains the previously delivered Floor (`FloorRRRouting=0`). This
build exposes two additional **experimental** routes under FSR-RR Advanced
Settings. It is not a claim that the TV grain in Screenshot (810) is fixed.

- `0 / Off (existing Floor)`: existing spatial pedestal, residual and
  Anchor/Correlation reconstruction.
- `1 / Automatic (flat regions)`: select locally flat, single-colour current RGB
  with flat, valid **original** diffuse and specular albedos. Full-confidence
  pixels send their signal to RR instead of Floor/Skip/detail. Ambiguous pixels
  use a continuous transition; detected texture retains the original partition.
- `2 / Force RR (selected surfaces)`: ignore current RGB texture, but still
  require the existing valid flat-albedo/surface support. It includes nonzero
  roughness flat surfaces, not just the legacy zero-roughness hint. This is not
  a global denoiser bypass and does not select mirrors with unusable diffuse
  albedo. It can blur animated text and reflections.

Both routes require Floor enabled. Mode changes reset the existing AMD RR
history. Invalid INI values fall back to zero. No virtual albedo, new temporal
accumulation, texture allocation, or new root-table entry is introduced.

## Selection and signal contract

Automatic selection examines a full 9x9 support. Canonical depth with a local
slope, original normal, original roughness and both original albedos must agree.
Unsupported image borders, material boundaries, invalid reference/radiance,
title bias and responsive content cannot lend support.

Nine 3x3 **RGB** block means measure structure; equal-luminance coloured text
therefore also vetoes flatness. A raw-RGB peak test protects isolated new pixels.
The seed sigma is capped by an independent median opposing-RGB-pair estimate:
a thin diagonal must not classify its own contrast as noise. This statistic is
an estimator, not proof that arbitrary correlated illumination is independent
fine noise. It has no camera/content-motion history.

For weight `w` in [0,1], the selected spatial pedestal is
`F'=(1-w)*min(F,C)` and RR receives `max(C-F',0)` through the existing quantized
albedo split. The title roughness is raised to **at least 0.1** if routing is
active; rougher surfaces are not lowered. This is an observed compatibility
value, **not a documented AMD threshold**. At w=1, no Floor pedestal or detail
graft remains. Title bias/responsivity routing and unavoidable demodulation /
storage remainder still follow the existing explicit contracts.

Skip RGB remains radiance. Negative Skip alpha stores `-w`; zero/positive alpha
keeps its prior diagnostic-luminance meaning. Composition scales **all** detail
corrections (including chroma/luma extensions) by `1-w`. Full routing also
invalidates the packed detail reference. `RROnlyRoute` displays the actual weight:
white=full, grey=partial, black=existing Floor. As with other conversion debug
views, use this to inspect selection, not to measure normal-game quality.

Packing constant offset 400 now stores `uint FloorRRRouting` in former padding;
the 416-byte constant-buffer size and all resource orders remain unchanged.
Signed RGBA16_FLOAT Skip alpha must not pass through a positive-radiance clamp.
Only RGB is sanitized. Feature descriptors, packing, debug routing and the
mirror validator were updated together.

## Why this is not the default

Actual AMD RR experiments showed that a changing per-pixel Floor subtraction
can produce temporal error near the flatness decision boundary. A softer mask
reduced but did not eliminate this failure. A separate rejected prototype fed
full radiance over the whole eligible material and selected only the output
detail: temporal noise dropped, but broad reflection contrast became worse.
That prototype is **not** the shipped automatic algorithm.

The production experiment is therefore opt-in. Flat-field improvement must not
be presented as general text/reflection improvement. Raising roughness cannot
guarantee successful RR reconstruction for missing or incompatible title inputs.
The default path is independently compared with the pre-change production DXIL.

## Reproducible validation

`test_fsrd_rr_routing.py` dispatches the real production DXIL for 0/1/2, full and
partial energy closure, flat/nonzero-roughness surfaces, RGB structure, new
one-pixel features, odd extents/subrects, HDR/exposure, title masks, surface
boundaries and full-routing suppression of detail reinjection. Existing quality
tests explicitly retain mode 0. They do not simulate an AMD quality pass.

`probe_fsrd_smooth_surface_rr.py` runs Seed, all five Floor passes, production
conversion, **actual AMD RR diffuse and specular**, and production composition.
The final probe covers flat, translating smooth-reflection and animated-text
scenes, 24 frames each at 128x96, using identical independent fine noise for the
three production modes. Metrics compare with independently generated clean
images. The package includes the results and shader/DLL hashes. D3D12 and AMD
SDK diagnostics must both be clean. These small synthetic scenes do not measure
game performance or prove game acceptance.

For the TV comparison, keep the same camera and Floor settings, change only
Advanced / Floor RR Routing between Off, Automatic and Force RR. Allow RR to
settle after each change. Inspect `RROnlyRoute` once to confirm whether the TV
actually qualifies, then compare `None` while still and under slight motion.
Also check an animated advertising screen so reduced grain is not mistaken for
preserved lettering. Automatic mixed-region flicker and forced-mode blur remain
known limitations, not completed fixes.
