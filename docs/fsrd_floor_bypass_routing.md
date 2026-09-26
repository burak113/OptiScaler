# Floor contribution routing during modulation bypass

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

## Reason for this diagnostic

The user reports that Bypass Specular Only removes the sea blotches with Floor
disabled, but they return with Floor enabled. Both SkipSignal and
ReconstructedColor contain the blotches. ReconstructedColor includes Skip; it
is not an isolated neural-denoiser output.

Previously, modulation bypass changed the selected lobe's division/multiplication
but left Floor's spatial pedestal in Skip. Thus the two Floor settings did not
send the same specular signal to RR. This is a confirmed routing difference,
not proof of the underlying cause of every sea artifact.

## Control

Advanced Settings -> Input Compatibility:

- Modulation Isolation (A/B): **Bypass Specular Only**.
- **Route Bypassed Lobes Through RR**: on for the new experiment, off for the
  previous routing. Keep Floor enabled when comparing. Switching resets history.

INI: `[FSR-RR] RouteBypassedFloor=true`. The default is true, but this setting
has no effect unless modulation bypass is selected. Off isolation preserves the
normal pipeline. The old Bypass Albedo Modulation checkbox also supports it.

## Accounting

Let C be raw color, F the spatial Floor estimate, b the explicit game bias mask,
and w the existing per-channel specular split. Previously RR received the split
of `(1-b)*max(C-F,0)` and Skip received `(1-b)*F+b*C`.

With specular bypass plus the new control:

- RR specular receives `(1-b)*C*w`, before the unchanged responsivity route.
- RR diffuse retains its original residual input.
- Floor's Skip pedestal becomes `(1-b)*F*(1-w)+b*C`.

Diffuse-only is symmetric. Both removes the whole spatial pedestal from Skip.
An estimate F greater than C cannot inflate the restored lobe: its input comes
directly from raw color. The unselected lobe can still retain its existing Floor
excess. Explicit bias/responsivity routing and genuinely unrepresentable FP16
energy are retained. Positive FP16 rounding loss is not copied back as grain
on the new route. Albedo guides, roughness, motion, and hit distance are not
rewritten by this control. Anchor/correlation/luma/chroma recovery is unchanged.

This adds arithmetic and a uniform branch to conversion, with no new dispatch,
texture allocation, neighborhood sample, or temporal history. It does not skip
the existing Floor filtering passes and is not a measured performance speedup.

## Validation and limits

The dedicated GPU suite executes production conversion/composition shaders with
patchy, excessive, dark-channel and HDR Floor estimates, direct/indirect paths,
partial/full game bias, and unresponsive specular. It checks selected-lobe
equivalence to Floor off within one FP16 storage step, bit-identical unselected RR inputs, guide/reprojection
preservation, energy closure, and explicit-mask retention. A frozen shader
comparison checks unchanged prior routing. Older modulation-isolation contracts
are rerun separately; delivery/verification.json records the completed checks.

The original split multiplication order is explicit to prevent DXC from changing
baseline FP16 rounding when the additional use of the split ratio is introduced.
The older specular-balance suite also checks exact baseline equivalence against
its frozen shader. The one-step tolerance applies only to the restored selected
lobe, not the normal off path.

These are routing tests with identity RR, not a Cyberpunk image-quality test or
a run of the AMD neural model. Specular-only can leave diffuse Floor artifacts.
Bypassing modulation can still soften fine detail. This build offers a controlled
A/B, not a claim that the sea is now fixed or that bypass should become permanent.

For an in-game comparison, leave other parameters fixed, allow history to settle,
and toggle only Route Bypassed Lobes Through RR. Compare None first, then
SkipSignal. Skip need not turn black in specular-only mode because diffuse Floor
and explicit bypass masks remain. If needed, Bypass Both distinguishes that
remaining contribution from the restored specular path.
