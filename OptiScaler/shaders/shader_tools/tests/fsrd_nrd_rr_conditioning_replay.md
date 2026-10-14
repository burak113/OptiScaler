This is a controlled signed AMD RR 1.2 research fixture. It changes no bridge,
configuration, shader, or signal defaults in the production DLL. Every noisy
diffuse/specular RGB sample is sent through the actual RRWrapper and signed
provider. There is no raw-lighting fallback or second denoiser.

The two experimental axes are DD+IS versus ID+IS and a fixed RGB gain of 1,
0.25, or 4. Each candidate uses a physically fresh context and the same complete
44-frame, 128 by 128 synthetic history from fsrd_nrd_quality_replay.py. Gain is
constant for the entire history. A test-only GPU pass multiplies owned RGBA16
signal RGB before RR; a second pass divides RR output RGB before the original
Consumer model and metrics. Alpha, hit distance, guides, camera, jitter, and
effective provider configuration are held constant between candidates.

The generator seals a NEW input manifest, rather than calling the old chosen
diffuse alpha7 a ray-traced first intersection. For every interior primary
surface point, the declared secondary diffuse sample is a normalized world+Z
ray. Its only forward intersection in the secondary ray-mask domain is the
emissive plane worldZ=+1. Its first-hit distance is therefore 1-primaryWorldZ:
approximately7 for the background and3 for the primary occluder. The reveal
occluder belongs to the primary visibility mask only. It is explicitly absent
from the secondary mask; it is not silently skipped as an opaque secondary
intersection. The 16-pixel guard contains nonphysical binding probes, is
excluded from metrics, and has positive alpha padding. Specular alpha5 remains
a disclosed chosen synthetic metric; this experiment does not attest a game's
specular path length or a combined-title-lighting decomposition.

AMD's documented ID alpha contract is an active indirect diffuse ray hit
distance. DD accepts an active finite nonnegative alpha without a ray-distance
meaning, so the exact same positive distance packet is legal for both routes.
The analytic radiance/checker/glossy reflection oracle is prescribed synthetic
radiance, not a physical renderer, native NRD output, or measured game footage.

Each run records exact signal flags/dispatch types, DLL and input hashes,
effective scalar values, reset/history sequence, context create/destroy counts,
strict D3D12 errors/warnings, opaque destination-alpha identity, staged SDK
hit-alpha identity, and GPU conditioning/denoising/Consumer timings. Guide and
input-alpha identity are checked after GPU execution. CPU image analysis uses
the same sealed reference and crop for all six candidates, and reports RGB
RMSE/bias, current-gradient error, reflection error, reveal response, opponent
chroma error, and motion-reprojected chroma-change error. It reports worse
candidates as well as better ones. Quality direction is never a pass condition.

The explicit FP16 gain pass uses nearest-even conversion, including subnormals;
its GPU bits are compared to an independent NumPy half conversion. Reciprocal
conditioning is not algebraically exact after half rounding. The report keeps
that quantization visible and never treats gain as an undocumented SDK exposure
field. All six candidates use one identical effective settings snapshot queried
from a disposable signed-provider defaults probe, and no per-frame adaptation.

Stage-alpha calibration is explicitly test-only. The documented output alpha
is "preserved (or input if passthrough)". That does not unambiguously say that
an out-of-place destination is filled with input alpha. Production's NewSlot
has uninitialized stage storage and its RGB-only commit ignores stage alpha.
The first uncontrolled setup therefore made an unsupported input-alpha-word
identity assumption. No provider defect follows from that failed assertion.
The separate --stage-alpha-diagnostic mode retains the strict interpretation,
saves raw bytes and full per-lobe/interior/padding statistics before assertion,
and never proceeds to quality candidates. The calibrated --run path initializes
both OWNED SDK stage textures with an exact CopyResource from actual conditioned
input RGBA before calling the signed provider. Input NPS and stage UAV states
are transitioned for copy and restored before dispatch; no title output is
written. This supports strict identity whether preservation means destination
alpha or input passthrough. Copy timing is reported separately from RR/commit.
The initialization option is immutable for a whole history. It adds no
production default or production shader/resource behavior.

Compilation and every native execution must be scheduled by the lead through
lead_ops/run_task_test.py and its machine-wide GPU lock. Source preparation is
allowed while the compiler/GPU queue is held; preparing these files does not
mean the experiment has run. The old RR wrapper fixture remains unchanged and
its original camera, failure, alpha, codec, and deferred-lifetime assertions are
still separate required regressions.

Primary API reference:
https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/blob/main/Kits/FidelityFX/docs/techniques/denoising.md

Scope: synthetic signed-provider hypothesis test. No production default change,
native NRD comparison, game quality improvement, or game FPS claim follows from
the existence of this fixture.
