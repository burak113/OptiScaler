# Captured glass policy fixture

Run `python test_glass.py` or `python glass_fixture.py analyze`. The only dependency beyond Python's standard library is NumPy. No GPU, RR Lab, private capture directory or game installation is needed.

`glass_crop.npz` is a compact crop from published capture `87ee1fba-b8bc-4660-aa3f-d06db7bf863f`, frames 46–63, camera-aligned to frame 54. `manifest.json` gives the exact crop, frozen mask count, exposure, formulas, source payload hashes and expected metrics. It stores aligned raw specular RGB as float32 and the selected RGB as lossless uint32 XOR against raw; the loader restores every selected float32 bit. Equal diffuse RGB is a separate aligned field. Original packed normals/roughness uint32, depth float32, motion RGBA float16 and camera uint32 words retain their original stored dtypes. Those original geometry/motion crops are unwarped; aligned masks are explicitly separate.

**There is no ground truth.** Raw is captured RR output; selected is captured **old NZR**, not a reference image for a new algorithm. These data reproduce a glass policy trade-off, not a new algorithm or final-DLL game screenshot. Use one frozen mask for every variant. Grain and detail are separate metrics; do not merge them into a quality score.

Blend uses `raw + float32(k) * (selected - raw)`, with `k=0.5` or `0.75`. The mask selects fully vertical glass (`abs(nz)<=0.5`), so the production orientation gate is one. Temporal CV is luma temporal standard deviation divided by temporal mean. High-pass CV subtracts an edge-clamped separable sigma-2 Gaussian first. Detail is mean absolute sigma-1.5 high-pass of the temporal mean. A six-pixel crop halo is excluded from the frozen mask.

`full_roi_evidence.json` separately records the earlier **8048-pixel full 512×512 ROI** result. It is not the small fixture's count or expected result. The small fixture composes aligned specular and diffuse; the prior full-ROI protocol composes before camera sampling. Their tiny rounding difference and crop scopes are explicitly separated. Camera alignment uses reference depth and P00/P11 camera reprojection, without source-depth occlusion checking or dynamic-motion compensation; this is a measurement limitation.

To regenerate from an accessible copy of the original capture, run:

`python glass_fixture.py export --source-capture PATH_TO_CAPTURE --out OUTPUT_DIRECTORY`

The exporter reads only published frames and never writes the source capture. It also recalibrates the full-ROI result against the previously measured 8048-pixel statistics before exporting the smaller fixture. No absolute source path is placed in the fixture metadata.

The bundled crop is 192 x 160 pixels at ROI coordinates [50, 180, 242, 340], with 6497 common eligible pixels after its six-pixel halo. Its compressed data file is 19,310,928 bytes. The separately recorded full-ROI mask has 8048 pixels.
