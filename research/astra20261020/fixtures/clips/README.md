# Chronological CPU research clips

Python 3 + NumPy only. No RR DLL, GPU, Windows API, absolute host paths or shared library is needed to load/test these fixtures.

These are **dry research fixtures, not ground truth**. Captured raw/selected RR outputs retain history from before the exported interval. Every clip has partial history; do not run the first frame against the last frame, repeat noise realizations, or claim that these clips replay the original RR context. The final upscaler/game display is absent. Albedos are omitted, so these are not complete seven-input RR dispatch fixtures.

Files:

- `bottle_track7.npz`: source 2405579e, original frames 180..186 inclusive; 128x256 moving crops. Local source y origins 160,176,208,272,384,480,560; local x=0. Source ROI global origin=(688,0). The fixed original speed>12px/erode2 mask includes bottle plus hand/arm. All original mask pixels remain inside each track crop; previous samples for frames181..186 remain inside the preceding crop.
- `foliage23.npz`: source 87ee1fba, frames43..65; source-local x256:448,y256:320 (192x64). Global origin=(752,423). This band contains multiple depth/coverage layers and is not a semantic material mask.
- `facade16.npz`: source f2ef375f, frames34..49; source-local x192:288,y192:288 (96x96). This small tile is not the original whole-ROI calibrated bench mask.

Each archive contains the ten original typed fields, original 46-word uint32 provider controls, original capture frame indices, per-frame global render crop origins, local source crop origins, original render/source ROI extents, and original camera/projection/position word arrays. The adjacent JSON records exact source identities, per-file SHA256, per-crop raw-byte SHA256 and array/archive SHA256. Source filenames are relative to the source capture UUID. The selected-input aggregate covers the selected **full source files**, not every file of the full capture; its framing/order is specified in JSON. Camera arrays are copied from the manifest, whose full SHA256 is recorded.

Radiance remains captured FP16 RGBA in physical units. Input alpha contains the original hit distance; do not discard it. Packed normals/roughness remain uint32 words: oct normal bits 0..19, linear roughness bits 20..29, material bits 30..31. The source's original material IDs are globally 0 in all published 2405/87ee frames; they cannot supply semantic glass/foliage classes. Provider and original packed guides are both included because their lower 30 bits can differ. No global material claim is made for the facade capture.

Motion RG stays in **physical full-render UV**, previous minus current, with no extra jitter delta or crop scaling. With a local integer pixel coordinate `p`:

```
previous_local = p + crop_origin_render[t]
                 + input_motion[t, ..., :2] * render_extent
                 - crop_origin_render[t-1]
```

For bilinear sampling, require finite coordinates and `0<=qx<width-1`, `0<=qy<height-1`. Outside-crop history is invalid; do not clamp or wrap. Motion B is previous-minus-current linear depth. The first fixture frame has no available previous image. World-space normals need no camera-basis rotation.

Offline validation:

```
python test_clips.py
```

Independent source-backed validation, when the original captures are available:

```
python test_clips.py --trace-root /path/to/GAME_TRACE
```

Re-export from original captures into a new directory:

```
python export_clips.py --trace-root /path/to/GAME_TRACE --out ./new_clips
```

Use `--overwrite` only to intentionally replace existing fixtures. Export verifies full source image hashes against the original capture manifest, preserves original dtypes/words, and performs no filtering, interpolation, color normalization or exposure. `clip_loader.py` supplies the loader and origin-aware previous-coordinate/bilinear helpers. The latter returns NaN for invalid samples, while all stored original floating arrays are finite. `validation.json` records the executed checks; it contains no private host paths.
