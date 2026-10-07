"""Independent D3D12 contracts for a coherent-lighting Floor certificate.

The certificate is exact FloorModel RGB [-101, -101, -101], with its original
alpha retained. The qualified current raw class changes only protected final
conversion stores: Skip RGB and packed reference RGB become safe FP16 raw.
Seed reference RGB/A stay unchanged so raw restoration cannot alter selection,
source weights, routing or submitted native-history lobes.
Separate -102 marks a qualified local spatial projection, whose current mean
is retained by Floor. It does not grant an authoritative raw/Skip certificate.
The accepted-raw and quiet-current-mean interfaces are tested separately.
Unprotected packed reference RGB and every reference alpha retain their current
unmarked-model control. Projection may intentionally change Floor and its native residual.
Analytic lighting truth, independent stochastic fields, geometry/material seams,
and forged-certificate exclusion probes exercise that distinction.

No CPU implementation of the production coherence classifier is used. Production
Seed, Floor, conversion and composition DXIL execute on D3D12. Composition uses
explicit identity or poisoned RR inputs here, not a simulated denoiser or an AMD
quality claim. Native AMD quality acceptance remains a separate required suite.
TileAnchor owns handover tiles only: its standalone selected-screen probes are
meaningful, while ordinary-only final output is owned by the supported light/full
variants. The shared-UAV TileLight/TileAnchor pair is validated by the native
driver suite rather than reading an unwritten standalone TileAnchor output.

The no-argument CLI runs this normal validation suite; --describe is CPU-only.
Each run makes a fresh immutable candidate/control snapshot and private runner.
The automatic control disables only the two new Seed producers via the test
macro; all consumer assets stay identical. This is a semantic protocol control,
not the original49b native quality baseline. An explicit C19 directory remains
an optional diagnostic control. --run is a backwards-compatible execution alias.
The independent sparse control disables only the supported-background uplift;
its compact causal probes never depend on an old candidate directory.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import traceback
import shutil
import re
import tempfile
from datetime import datetime, timezone

import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as c


TAG = -101.0
PROJECTION_TAG = -102.0
PROJECTION_ULP_LIMIT = 4.5
CONTROL_MACRO = 'FSRD_FLOOR_REFERENCE_TEST_CONTROL'
SPARSE_CONTROL_MACRO = 'FSRD_FLOOR_SPARSE_TEST_CONTROL'
# The coherent-lighting witness (-101) and local projection (-102) Seed
# producers left the default Seed for cost: they never fired on captured game
# frames. They remain in the opt-in FloorCleanLighting PSO variant, which
# defines FSRD_FLOOR_CLEAN_LIGHTING 1. When the Seed under test does not enable
# them, checks that only exist to demand their coverage are reported, not gated.
RETIRED_PRODUCERS = False


def _producers_retired(source_text):
    if 'g_CoherentLighting' not in source_text:
        return True
    definitions = re.findall(r'^\s*#\s*define\s+FSRD_FLOOR_CLEAN_LIGHTING\s+(\S+)', source_text, re.MULTILINE)
    return bool(definitions) and all(value == '0' for value in definitions)


def _producer_check(name, passed, **metrics):
    if RETIRED_PRODUCERS:
        print(f'RETIRED (report only) {name} measured_pass={bool(passed)} {metrics}', flush=True)
    else:
        t.check(name, passed, **metrics)
ZERO_SLOPE = -100.0
FULL = (1, 2, 4, 8, 16)
FAST = (1, 2, 16)
EXPOSURES = (.03125, 1., 2048.)
# These independent probe bounds do not replace or change any quality-suite gate.
BOUNDS = dict(clean_channel_rmse=.003, clean_channel_bias=.0015,
              clean_channel_peak=.012, clean_gain_min=.98, clean_gain_max=1.02,
              clean_tag_min_pixels=16, clean_tag_min_fraction=.01,
              identity_relative=.002, identity_absolute=.00002,
              cluster_reference_rejection=.02, cluster_skip_rejection=.05,
              boundary_tag_count=0, noise_tag_count=0)
WAVE_SPECS = ((71, 53, .085, .19), (83, 61, .137, .73),
              (95, 67, .193, 1.31), (107, 73, .271, 2.17))
RESOLVED_FREQUENCY = .85
RESOLVED_ANGLE = .73
RESOLVED_PHASES = (0., .77, 1.83)
NOISE_SPECS = (('white RGB', 17011), ('white common mode', 28123),
               ('correlated coloured grain', 39043))
COMPOSITION_VARIANTS = ('FSRDOutputComp', 'FSRDOutputCompLight',
                        'FSRDOutputCompNoRecovery', 'FSRDOutputCompTileAnchor')
CERTIFICATE_INTERFACE = 'qualified raw final conversion source -101; separate quiet current spatial mean -102'


@dataclass
class Frame:
    name: str
    raw: np.ndarray
    truth: np.ndarray
    albedo: np.ndarray
    depth: np.ndarray
    normals: np.ndarray
    exposure: float
    requires_certificate: bool = False
    requires_projection: bool = False


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _array_hash(value):
    value = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(str(value.dtype).encode())
    digest.update(json.dumps(value.shape).encode())
    digest.update(value.tobytes())
    return digest.hexdigest()


def _dependency_identity():
    here = Path(__file__).resolve().parent
    result = {name: _hash(here / name) for name in (
        Path(__file__).name, 'run_fsrd_gpu_tests.py', 'fsrd_alpha_common.py',
        'fsrd_gpu_runner.cpp')}
    for name in ('build_fsrd_shader.py', 'fsrd_toolchain.py'):
        result['../' + name] = _hash(here.parent / name)
    return result


def _asset_identity(directory):
    return {path.name: _hash(path) for path in sorted(Path(directory).iterdir())
            if path.is_file() and path.suffix in ('.hlsl', '.hlsli', '.cso', '.h')}


def _manifest(directory, *, purpose, defines, **metadata):
    data = dict(purpose=purpose, defines=defines, files=_asset_identity(directory), **metadata)
    (Path(directory).parent / 'shader_manifest.json').write_text(
        json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    return data


def _snapshot(source, target, purpose):
    source, target = Path(source).resolve(), Path(target).resolve()
    before = _asset_identity(source)
    if not before:
        raise ValueError('Shader snapshot source is empty')
    if target.exists() and any(target.iterdir()):
        raise ValueError('Shader snapshot target must be new or empty')
    target.mkdir(parents=True, exist_ok=True)
    for name in before:
        shutil.copyfile(source / name, target / name)
    if before != _asset_identity(source) or before != _asset_identity(target):
        raise RuntimeError('Source changed while freezing shader assets')
    _manifest(target, purpose=purpose, defines={CONTROL_MACRO: 0},
              source=str(source), source_files=before)
    return before


def _automatic_control(candidate, control, *, macro=CONTROL_MACRO):
    """Compile only Seed in short private staging, then audit the final snapshot.

    DXC's temporary output filenames can exceed Windows MAX_PATH in nested CI
    suite outputs even when the source and final assets are readable. Preserve
    the self-contained deep snapshot, but give the normal builder short paths.
    """
    import build_fsrd_shader as build
    from fsrd_toolchain import dxc
    source = (candidate / 'FSRDFloorSeed.hlsl').read_bytes()
    _require_default_producers(source)
    if macro not in (CONTROL_MACRO, SPARSE_CONTROL_MACRO):
        raise ValueError('Unknown Seed semantic control')
    if macro == SPARSE_CONTROL_MACRO:
        _require_default_macro(source, SPARSE_CONTROL_MACRO)
    purpose = 'disabled_new_seed_producers' if macro == CONTROL_MACRO else 'disabled_sparse_uplift_only'
    defines = {CONTROL_MACRO: 1} if macro == CONTROL_MACRO else {CONTROL_MACRO: 0, SPARSE_CONTROL_MACRO: 1}
    _snapshot(candidate, control, purpose)
    (control / 'FSRDFloorSeed.hlsl').write_bytes(
        ('#define ' + macro + ' 1\n').encode() + source)
    compiler = dxc()
    staging_parent = (t.ROOT / 'tools_tmp').resolve()
    staging_parent.mkdir(parents=True, exist_ok=True)
    staged_inputs = _asset_identity(control)
    compiled_assets = ('FSRDFloorSeed_Shader.cso', 'FSRDFloorSeed_Shader.h')
    with tempfile.TemporaryDirectory(prefix='fsrdlc_', dir=staging_parent) as temporary:
        staging_root = Path(temporary).resolve()
        # Bound the generated checkout and its cleanup to this known directory.
        if staging_root.parent != staging_parent or not staging_root.name.startswith('fsrdlc_'):
            raise RuntimeError('Private Seed staging escaped the intended tools_tmp directory')
        staged = staging_root / 'precompile'
        expected_temporary = staged / 'FSRDFloorSeed_12345678' / 'FSRDFloorSeed.cso'
        if len(str(expected_temporary)) >= 240:
            raise ValueError('Private Seed build staging is too long for DXC temporary outputs')
        _snapshot(control, staged, 'short_private_seed_build')
        if _asset_identity(staged) != staged_inputs:
            raise RuntimeError('Private Seed staging differs from the exact control inputs')
        prior = build.ROOT, build.PRE
        try:
            build.ROOT, build.PRE = str(staging_root), staged.name
            build.build('FSRDFloorSeed', compiler)
        finally:
            build.ROOT, build.PRE = prior
        staged_outputs = _asset_identity(staged)
        if staged_outputs.keys() != staged_inputs.keys() or any(
                staged_inputs[name] != staged_outputs[name]
                for name in staged_inputs if name not in compiled_assets):
            raise RuntimeError('Private Seed compilation changed an input or non-Seed asset')
        if _asset_identity(control) != staged_inputs:
            raise RuntimeError('Deep control snapshot changed during its private Seed build')
        for name in compiled_assets:
            shutil.copyfile(staged / name, control / name)
        if _asset_identity(control) != staged_outputs:
            raise RuntimeError('Published control does not match the audited private Seed build')
    changed = {'FSRDFloorSeed.hlsl', 'FSRDFloorSeed_Shader.cso', 'FSRDFloorSeed_Shader.h'}
    candidate_files, control_files = _asset_identity(candidate), _asset_identity(control)
    if candidate_files.keys() != control_files.keys() or any(
            candidate_files[name] != control_files[name] for name in candidate_files if name not in changed):
        raise RuntimeError('Automatic control changed a non-Seed asset')
    if (control / 'FSRDFloorSeed.hlsl').read_bytes() != (
            ('#define ' + macro + ' 1\n').encode() + source):
        raise RuntimeError('Producer-disabled source lost its exact override')
    _manifest(control, purpose=purpose, defines=defines,
              compiled_only=['FSRDFloorSeed'], unchanged_consumers=True,
              candidate_files=candidate_files, compiler=str(compiler), compiler_sha256=_hash(compiler),
              compilation_staging=dict(strategy='short_private_workspace_temporary',
                                       inputs=staged_inputs, outputs=staged_outputs,
                                       published_assets=list(compiled_assets),
                                       audited_same_contents=True))


def _require_default_producers(source):
    _require_default_macro(source, CONTROL_MACRO)


def _require_default_macro(source, macro):
    text = source.decode('utf-8')
    pattern = rf'#ifndef\s+{macro}\s+#define\s+{macro}\s+0\s+#endif'
    definitions = re.findall(rf'^\s*#\s*define\s+{macro}\s+([^\r\n]+)', text, re.MULTILINE)
    if re.search(pattern, text) is None or definitions != ['0']:
        raise ValueError('Candidate Seed must declare exactly one ' + macro + ' with default0')


def _frozen_identity(directory):
    directory = Path(directory).resolve()
    if directory == t.PRE.resolve():
        raise ValueError('Use an immutable shader snapshot, not working production')
    manifest_path = directory.parent / 'shader_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    records = manifest.get('files', manifest)
    if not isinstance(records, dict) or not records:
        raise ValueError('Frozen shader manifest has no file hashes')
    for name, expected in records.items():
        if Path(name).name != name or _hash(directory / name) != expected:
            raise ValueError('Frozen shader hash mismatch: ' + name)
    required = ['FSRDFloorModel.hlsli']
    for shader in ('FSRDFloorSeed', 'FSRDFloor', 'FSRDInputConv') + COMPOSITION_VARIANTS:
        required += [shader + '.hlsl', shader + '_Shader.cso']
    if any(name not in records for name in required):
        raise ValueError('Frozen manifest omits a dispatched shader or model contract')
    return dict(directory=str(directory), manifest_sha256=_hash(manifest_path),
                purpose=manifest.get('purpose', 'explicit_frozen_diagnostic'),
                defines=manifest.get('defines', {}), files=records)


def _frame(name, rgb, exposure=1., albedo=None, depth=None, normals=None,
           requires_certificate=False):
    h, w = rgb.shape[:2]
    albedo = t.rgba(w, h, (.48, .52, .44)) if albedo is None else albedo
    depth = np.full((h, w), 10., np.float32) if depth is None else depth
    normals = t.rgba(w, h, (0, 0, -1)) if normals is None else normals
    truth = c.rgba(np.asarray(rgb, np.float32) * exposure)
    return Frame(name, truth.copy(), truth, albedo, depth, normals, exposure, requires_certificate)


def _wave(w, h, frequency, angle):
    # Independent channel directions and phases ensure a luminance-only detector
    # or colour-preservation metric cannot stand in for the RGB contract.
    y, x = np.indices((h, w), dtype=np.float64)
    x -= (w - 1) / 2
    y -= (h - 1) / 2
    rgb = np.empty((h, w, 3), np.float32)
    for channel, (offset, amplitude, phase, rotation) in enumerate((
        (.39, .17, .21, 0.), (.44, .19, 1.17, .61), (.47, .16, 2.37, -.53))):
        theta = angle + rotation
        along = np.cos(theta) * x + np.sin(theta) * y
        across = -np.sin(theta) * x + np.cos(theta) * y
        rgb[..., channel] = (offset + amplitude * np.sin(frequency * along + phase)
                             + (.027 + .006 * channel) *
                             np.cos(frequency * (.71 + .08 * channel) * across + phase + .14))
    return rgb


def clean_frames():
    for w, h, frequency, angle in WAVE_SPECS:
        for exposure in EXPOSURES:
            name = f'wave_{w}x{h}_k{frequency}_theta{angle}_exposure{exposure}'
            yield _frame(name, _wave(w, h, frequency, angle), exposure)


def _resolved_light(w, h, phase):
    # This new family has real mixed-XY curvature above FP16 uncertainty. Its
    # channel phases differ; neither common-mode white grain nor a luminance
    # pattern alone describes this known clean lighting.
    y, x = np.indices((h, w), dtype=np.float64)
    x -= (w - 1) / 2
    y -= (h - 1) / 2
    kx = RESOLVED_FREQUENCY * np.cos(RESOLVED_ANGLE)
    ky = RESOLVED_FREQUENCY * np.sin(RESOLVED_ANGLE)
    rgb = np.empty((h, w, 3), np.float32)
    for channel, (offset, amplitude, channel_phase) in enumerate((
        (.39, .17, .21), (.44, .19, 1.17), (.47, .16, 2.37))):
        rgb[..., channel] = (offset + amplitude *
            np.sin(kx * x + phase + channel_phase) *
            np.sin(ky * y - .63 * phase + .71 * channel_phase))
    return rgb


def resolved_frames():
    w, h = 87, 63
    for phase in RESOLVED_PHASES:
        for exposure in EXPOSURES:
            name = f'resolved_mixedXY_k{RESOLVED_FREQUENCY}_theta{RESOLVED_ANGLE}_phase{phase}_exposure{exposure}'
            yield _frame(name, _resolved_light(w, h, phase), exposure,
                         requires_certificate=True)


def polynomial_frames():
    """Analytic low-degree lighting truth, independently of the fitted kernel."""
    w, h = 81, 57
    y, x = np.indices((h, w), dtype=np.float64)
    u, v = 2 * x / (w - 1) - 1, 2 * y / (h - 1) - 1
    fields = (
        ('quadratic', np.stack((.42 + .12*u*u + .06*u*v - .05*v,
                                .48 - .09*v*v + .045*u,
                                .37 + .08*v*v + .055*u*v), axis=-1)),
        ('cubic', np.stack((.42 + .09*u**3 + .03*u*v*v - .04*v + .02*u*u,
                            .48 - .065*v**3 + .055*u*u*v + .04*u,
                            .37 + .07*u*v*v - .05*u*u*v + .04*v), axis=-1)),
    )
    for degree, rgb in fields:
        for exposure in EXPOSURES:
            frame = _frame(f'analytic_{degree}_lighting_exposure{exposure}', rgb, exposure)
            frame.requires_projection = True
            yield frame


def _resolution_physics(frame):
    """Independent signal/rounding proof, not a production classifier oracle.

    Delta_xx Delta_yy of a sinusoid has response
    16*sin(kx/2)^2*sin(ky/2)^2, hence O(k^4). Propagate the worst half-ULP
    storage error through this diagnostic linear operator. Broad lighting can
    be preserved without making a numerically unsupported certificate. The
    new fine family resolves mixed curvature in at least two RGB channels.
    No production ratio, PSD rule, eligibility rule or tag prediction is used.
    """
    rgb = np.asarray(frame.truth[..., :3], np.float64)
    stored = rgb.astype(np.float16)
    high = np.nextafter(stored, np.float16(np.inf)).astype(np.float64)
    low = np.nextafter(stored, np.float16(-np.inf)).astype(np.float64)
    epsilon = .5 * np.maximum(high - stored, stored - low)
    difference = np.zeros((rgb.shape[0] - 2, rgb.shape[1] - 2, 3), np.float64)
    uncertainty = np.zeros_like(difference)
    for yy, cy in enumerate((1., -2., 1.)):
        for xx, cx in enumerate((1., -2., 1.)):
            coefficient = cx * cy
            selection = (slice(yy, yy + difference.shape[0]),
                         slice(xx, xx + difference.shape[1]), slice(None))
            difference += coefficient * rgb[selection]
            uncertainty += abs(coefficient) * epsilon[selection]
    ratio = np.abs(difference) / uncertainty
    resolved = np.sum(ratio > 1., axis=-1) >= 2
    passed = (int(resolved.sum()) >= 100 if frame.requires_certificate
              else float(ratio.max()) <= 1.)
    return dict(name=frame.name, expects_resolved_curvature=frame.requires_certificate,
                maximum_signal_to_rounding_bound=float(ratio.max()),
                channel_maximum_ratio=ratio.max(axis=(0, 1)).tolist(),
                two_channel_resolved_pixels=int(resolved.sum()),
                interior_pixels=int(resolved.size), classification_passed=passed)


def _smooth(value):
    # A generated random field, not a stand-in for Floor or a classifier oracle.
    result = np.asarray(value, np.float64)
    kernel = (1., 4., 6., 4., 1.)
    for axis in (0, 1):
        padded = np.pad(result, [(2, 2) if i == axis else (0, 0)
                                 for i in range(result.ndim)], mode='reflect')
        accum = np.zeros_like(result)
        for i, weight in enumerate(kernel):
            selection = [slice(None)] * result.ndim
            selection[axis] = slice(i, i + result.shape[axis])
            accum += weight * padded[tuple(selection)] / 16.
        result = accum
    return result


def noise_frames():
    w, h = 89, 65
    truth = np.broadcast_to([.39, .44, .47], (h, w, 3)).astype(np.float32)
    for name, seed in NOISE_SPECS:
        rng = np.random.default_rng(seed)
        if name == 'white RGB':
            noise = .052 * rng.standard_normal((h, w, 3))
        elif name == 'white common mode':
            common = rng.standard_normal((h, w, 1))
            noise = .052 * common * [.85, 1.05, .60]
            noise += .008 * rng.standard_normal((h, w, 3))
        else:
            fields = []
            for _ in range(2):
                field = _smooth(_smooth(rng.standard_normal((h, w))))
                fields.append((field - field.mean()) / field.std())
            noise = (.040 * fields[0][..., None] * [.72, 1.10, .64]
                     + .028 * fields[1][..., None] * [-.55, .35, 1.05]
                     + .009 * rng.standard_normal((h, w, 3)))
        for exposure in (.125, 128.):
            frame = _frame(f'{name}_seed{seed}_exposure{exposure}', truth, exposure)
            frame.raw = c.rgba(np.maximum(truth + noise, .02) * exposure)
            yield frame


def cluster_frames():
    w, h = 79, 59
    truth = np.broadcast_to([.22, .24, .28], (h, w, 3)).astype(np.float32)
    centers = np.zeros((h, w), bool)
    centers[23:25, 31:33] = True
    centers[26:28, 34:36] = True
    peak_channel = np.zeros((h, w), np.int64)
    peak_channel[26:28, 34:36] = 1
    for exposure in (.125, 16.):
        frame = _frame(f'two_coloured_2x2_clusters_exposure{exposure}', truth, exposure)
        frame.raw[23:25, 31:33, :3] = np.array([.94, .58, .42]) * exposure
        frame.raw[26:28, 34:36, :3] = np.array([.43, .93, .54]) * exposure
        yield frame, centers, peak_channel


def boundary_frames():
    w, h = 91, 69
    y, x = np.indices((h, w))
    side = x >= w // 2
    rng = np.random.default_rng(47237)
    right = np.array([.18, .22, .25]) + .04 * rng.standard_normal((h, w, 1))
    right += .008 * rng.standard_normal((h, w, 3))
    for family, rgb, requires_certificate in (
        ('', _wave(w, h, .137, .53), False),
        ('resolved_', _resolved_light(w, h, .77), True),
    ):
        rgb[side] = np.maximum(right[side], .02)
        for kind in ('depth', 'normal', 'albedo'):
            frame = _frame(family + 'coherent_to_grain_' + kind + '_seam', rgb,
                           requires_certificate=requires_certificate)
            if kind == 'depth':
                frame.depth[side] = 3.
            elif kind == 'normal':
                frame.normals[side, :3] = [0, .8, -.6]
            else:
                frame.albedo[side, :3] = [.21, .28, .19]
            boundary = (np.abs(x - (w // 2 - .5)) < 2) & (y >= 3) & (y < h - 3)
            left = (x >= 4) & (x < w // 2 - 4) & (y >= 4) & (y < h - 4)
            right_roi = (x >= w // 2 + 4) & (x < w - 4) & (y >= 4) & (y < h - 4)
            yield frame, boundary, left, right_roi


def _identity(frame):
    return dict(name=frame.name, extent=list(frame.raw.shape[:2][::-1]),
                exposure=frame.exposure,
                requires_positive_certificate=frame.requires_certificate,
                arrays={name: _array_hash(getattr(frame, name))
                        for name in ('raw', 'truth', 'albedo', 'depth', 'normals')})


def _sparse_frame(name, count, *, exposure=1., quiet=False, mixed=False,
                  background=(.018, .018, .018), dark=None, impulse=False):
    """Exact binary geometry; material/radiance are independent analytic fields."""
    w, h = 37, 29
    cy, cx = 14, 18
    offsets = ((0, 0), (-1, 0), (1, 0), (0, -2), (0, 2), (-2, -1), (2, 1), (1, 2))
    levels = (.50, .40, .60, .45, .55, .475, .525, .42)
    raw = t.rgba(w, h, background)
    albedo = t.rgba(w, h, (.50, .45, .525))
    normals = t.rgba(w, h, (0, 0, 1))
    depth = np.full((h, w), 10., np.float32)
    coordinates = []
    for index, (dx, dy) in enumerate(offsets[:count]):
        y, x = cy + dy, cx + dx
        coordinates.append((y, x))
        normals[y, x, :3] = [0, 0, -1]
        albedo[y, x, :3] = np.array([1., .9, 1.05]) * levels[index]
        if dark is not None and index == 1:
            albedo[y, x, 1] = dark
        raw[y, x, :3] = (np.array([.07, .09, .11]) if quiet else
                        np.array([.58, .62, .56]) - np.array([.20, .22, .18]) * albedo[y, x, :3])
        if mixed:
            raw[y, x, 0] = .8 * albedo[y, x, 0] + .06
    if quiet:
        raw[..., :3] = [.07, .09, .11]
    if impulse:
        raw[cy, cx, :3] = [1.20, .75, 1.05]
    raw[..., :3] *= exposure
    frame = Frame(name, raw, raw.copy(), albedo, depth, normals, exposure)
    return frame, dict(centre_yx=[cy, cx], same_geometry_yx=coordinates, same_geometry_count=count)


def sparse_frames():
    """Sixteen frozen causal probes; no old shader directory is their oracle."""
    for count in (3, 5, 8):
        yield (*_sparse_frame(f'unsupported_{count}_same_surface_taps', count), 'uplift')
    yield (*_sparse_frame('unsupported_5_HDR', 5, exposure=128.), 'uplift')
    yield (*_sparse_frame('quiet_additive_same_surface_pedestal', 5, quiet=True), 'quiet')
    yield (*_sparse_frame('R_positive_model_GB_unsupported', 5, mixed=True), 'mixed')
    for count in (1, 2):
        yield (*_sparse_frame(f'isolated_{count}_geometry_taps', count), 'insufficient')
    yield (*_sparse_frame('chromatic_positive_centre', 5, impulse=True), 'impulse')
    for background in ((.002, .003, .004), (.90, .75, .60)):
        yield (*_sparse_frame('cross_normal_background_' + str(background), 5, background=background), 'cross')
    for value, kind in ((.01953125, 'one dark G guide below minimum'),
                        (.20, 'one G guide makes query/minimum gain exceed two')):
        yield (*_sparse_frame(kind, 5, dark=value), 'guide')
    for centre in (.434570313, .434814453):
        frame, meta = _sparse_frame('one_ULP_predicate_transition_' + str(centre), 3)
        frame.normals[..., :3] = [0, 0, 1]
        frame.albedo[..., :3] = .5
        frame.raw[..., :3] = 0.
        cy, cx = meta['centre_yx']
        coordinates = [(cy, cx - 2), (cy, cx - 1), (cy, cx)]
        for y, x in coordinates:
            frame.normals[y, x, :3] = [0, 0, -1]
            frame.raw[y, x, :3] = .399902344
        frame.raw[cy, cx, :3] = centre
        frame.truth = frame.raw.copy()
        meta['same_geometry_yx'] = coordinates
        yield frame, meta, 'ulp'
    frame, meta = _sparse_frame('zero_background_positive_impulse', 5, background=(0, 0, 0))
    frame.raw[..., :3] = 0.
    frame.raw[14, 18, :3] = [1.2, .75, 1.05]
    frame.truth = frame.raw.copy()
    yield frame, meta, 'zero'


def sparse_adversarial_frames():
    """Three separately frozen frames for cluster/minimum and guide continuity."""
    cy, cx = 14, 18
    def blank(name):
        raw = t.rgba(37, 29, (0, 0, 0))
        return Frame(name, raw, raw.copy(), t.rgba(37, 29, (.5, .5, .5)),
                     np.full((29, 37), 10., np.float32), t.rgba(37, 29, (0, 0, 1)), 1.)
    frame = blank('four_bright_one_quiet_same_surface_population')
    coords = [(cy, cx), (cy, cx-1), (cy, cx+1), (cy-2, cx), (cy+2, cx)]
    for y, x in coords:
        frame.normals[y, x, :3] = [0, 0, -1]
        frame.raw[y, x, :3] = 8.
    frame.raw[cy+2, cx, :3] = .25
    frame.truth = frame.raw.copy()
    yield frame, dict(centre_yx=[cy, cx], same_geometry_yx=coords, same_geometry_count=5), 'cluster'
    for guide in (.25, .24987793):
        frame = blank('one_ULP_middle_guide_' + str(guide))
        coords = [(cy, cx-2), (cy, cx-1), (cy, cx)]
        for (y, x), material in zip(coords, (.5, guide, .5)):
            frame.normals[y, x, :3] = [0, 0, -1]
            frame.albedo[y, x, :3] = material
            frame.raw[y, x, :3] = .399902
        frame.truth = frame.raw.copy()
        yield frame, dict(centre_yx=[cy, cx], same_geometry_yx=coords, same_geometry_count=3), 'guide_ulp'


MODEL_TRANSPORT_STEPS = (1, 2, 4, 8, 16)
MODEL_TRANSPORT_BOUND = dict(log_model_half_ulps=1., fp32_log_absolute=1e-6)


def model_transport_frames():
    """Twenty one-pass coefficient probes with closed-form material truth.

    Constant geometry/albedo/radiance gives unit surface/appearance weights.
    The four axial taps each weigh1/2; diagonal taps each weigh1/4. Rejected
    coefficients are absent estimates, while accepted coefficients are known
    exact powers of two. The expectations do not implement the shader filter.
    """
    w = h = 65
    for cohort in ('missing', 'mixed', 'positive_constant', 'rejected_classes'):
        for step in MODEL_TRANSPORT_STEPS:
            color = t.rgba(w, h, (.5, .5, .5), .125)
            depth = np.ones((h, w), np.float32)
            guide = t.rgba(w, h, (0., 0., .5), .5)
            albedo = t.rgba(w, h, (.5, .5, .5))
            reference = color.copy()
            model = t.rgba(w, h, (ZERO_SLOPE,) * 3, 1.25)
            queries = [dict(yx=[32, 32], expected_log_rgb=[1., 2., 3.])]
            if cohort in ('missing', 'mixed'):
                model[32, 32, :3] = [1., 2., 3.]
            if cohort == 'mixed':
                unit_offsets = ((-1, -1), (1, 1), (1, -1), (-1, 1)) if step in (2, 8) else (
                    (-1, 0), (1, 0), (0, -1), (0, 1))
                payloads = ((ZERO_SLOPE, 1., 4.), (3., ZERO_SLOPE, 2.),
                            (2., 3., ZERO_SLOPE), (ZERO_SLOPE,) * 3)
                for (dx, dy), value in zip(unit_offsets, payloads):
                    model[32 + step * dy, 32 + step * dx, :3] = value
                # Two accepted taps per RGB channel, centre weight1.
                # Axial: (centre + .5*sum(valid taps))/2.
                # Diagonal: (centre + .25*sum(valid taps))/1.5.
                beta = (10/3, 13/3, 26/3) if step in (2, 8) else (4., 4.5, 9.)
                queries[0]['expected_log_rgb'] = np.log2(beta).tolist()
            if cohort in ('positive_constant', 'rejected_classes'):
                model[..., :3] = [1., 2., 3.]
            if cohort == 'rejected_classes':
                queries = []
                payloads = ((ZERO_SLOPE,) * 3, (TAG,) * 3,
                            (PROJECTION_TAG,) * 3, (ZERO_SLOPE, 2., ZERO_SLOPE))
                for (y, x), value in zip(((16, 16), (16, 48), (48, 16), (48, 48)), payloads):
                    model[y, x, :3] = value
                    queries.append(dict(yx=[y, x], expected_log_rgb=list(value)))
            yield dict(name=f'material_model_{cohort}_step{step}', cohort=cohort,
                       step=step, resources=[color, depth, guide, albedo, reference, model],
                       queries=queries, size=[w, h])


def _model_transport_identity(fixture):
    return dict(name=fixture['name'], cohort=fixture['cohort'], step=fixture['step'],
                extent=fixture['size'], srv_formats=[10, 41, 10, 10, 10, 10],
                uav_formats=[10, 10], queries=fixture['queries'],
                arrays={name: _array_hash(value) for name, value in zip(
                    ('color', 'depth', 'guide', 'albedo', 'reference', 'model'), fixture['resources'])})


def _model_log_storage_bound(expected):
    half = np.asarray(expected, np.float16)
    up = np.nextafter(half, np.float16(np.inf)).astype(np.float64)
    down = np.nextafter(half, np.float16(-np.inf)).astype(np.float64)
    spacing = np.maximum(np.abs(up - half), np.abs(half - down))
    return MODEL_TRANSPORT_BOUND['log_model_half_ulps'] * spacing + MODEL_TRANSPORT_BOUND['fp32_log_absolute']


def _model_transport_contract(directory, output):
    """Actual current Floor6SRV/2UAV; no old binary or control macro oracle."""
    if not t.floor_has_model(directory) or not t.floor_has_detail_reference(directory):
        raise ValueError('Material-model transport requires the current typed6SRV/2UAV Floor ABI')
    records = []
    for index, fixture in enumerate(model_transport_frames()):
        w, h = fixture['size']
        resources = fixture['resources']
        identity = _model_transport_identity(fixture)
        actual, model = t.dispatch('FSRDFloor',
            dict(DstTexSize=[w, h, 1/w, 1/h], StepSize=fixture['step'], AlbedoBase=[0, 0]),
            resources, [10, 10], (w, h), directory=directory)
        stored_color = resources[0].astype(np.float16).astype(np.float32)
        stored_model = resources[5].astype(np.float16).astype(np.float32)
        t.check(fixture['name'] + ': typed model readback and constant radiance/sigma fixed point',
                np.array_equal(_model(actual), model) and np.array_equal(actual, stored_color)
                and _model_transport_identity(fixture) == identity)
        t.check(fixture['name'] + ': material coefficient support cannot change noise alpha or source class',
                np.array_equal(model[..., 3], stored_model[..., 3])
                and np.array_equal(model[..., :3] > -99., stored_model[..., :3] > -99.)
                and np.array_equal(_tags(model), _tags(stored_model))
                and np.array_equal(_projections(model), _projections(stored_model)))
        query_results = []
        for query in fixture['queries']:
            y, x = query['yx']
            expected = np.asarray(query['expected_log_rgb'], np.float64)
            measured = model[y, x, :3].astype(np.float64)
            bound = _model_log_storage_bound(expected)
            delta = np.abs(measured - expected)
            t.check(fixture['name'] + f': closed-form RGB coefficient at({x},{y})',
                    np.all(delta <= bound), expected_log_rgb=expected.tolist(),
                    measured_log_rgb=measured.tolist(), allowance=bound.tolist(),
                    maximum_allowance_fraction=float(np.max(delta / bound)))
            if fixture['cohort'] in ('missing', 'rejected_classes'):
                t.check(fixture['name'] + f': absent estimates never dilute or authorize centre({x},{y})',
                        np.array_equal(model[y, x], stored_model[y, x]))
            query_results.append(dict(yx=[y, x], expected_log_rgb=expected.tolist(),
                                      measured_log_rgb=measured.tolist(), allowance=bound.tolist()))
        if fixture['cohort'] == 'positive_constant':
            t.check(fixture['name'] + ': all-positive constant coefficients remain byte exact everywhere',
                    np.array_equal(model, stored_model))
        path = output / f'model_transport_capture_{index:02}.npz'
        np.savez_compressed(path, color=resources[0], depth=resources[1], guide=resources[2],
                            albedo=resources[3], reference=resources[4], input_model=resources[5],
                            output_color=actual, output_model=model)
        records.append(dict(fixture=identity, queries=query_results,
                            capture=str(path), capture_sha256=_hash(path)))
    return records


def description():
    lights = list(clean_frames()) + list(resolved_frames())
    physics = [_resolution_physics(frame) for frame in lights]
    if not all(record['classification_passed'] for record in physics):
        raise AssertionError('CPU fixture resolution classification failed before GPU setup')
    frames = lights + list(noise_frames())
    frames += [frame for frame, _, _ in cluster_frames()]
    frames += [frame for frame, _, _, _ in boundary_frames()]
    return dict(purpose=__doc__, certificate_interface=CERTIFICATE_INTERFACE,
                tag_rgb=[TAG] * 3, retained_alpha=True,
                bounds=BOUNDS, full_steps=FULL, fast_steps=FAST,
                projection_tag_rgb=[PROJECTION_TAG] * 3,
                projection_query_limit_patch_ulp=PROJECTION_ULP_LIMIT,
                projection_fixture_records=[_identity(frame) for frame in polynomial_frames()],
                model_transport_bound=MODEL_TRANSPORT_BOUND,
                model_transport_fixture_records=[_model_transport_identity(fixture) for fixture in model_transport_frames()],
                sparse_fixture_records=[_identity(frame) for frame, _, _ in sparse_frames()],
                sparse_adversarial_fixture_records=[_identity(frame) for frame, _, _ in sparse_adversarial_frames()],
                sparse_control_macro=SPARSE_CONTROL_MACRO,
                resolution_physics=physics,
                stale_rr_guard='Skip.A=-1; submitted native lobes and Seed reference stay unchanged; final source is qualified raw once',
                composition_variants=COMPOSITION_VARIANTS,
                fixture_records=[_identity(frame) for frame in frames],
                manual_probe_extent=[37, 29],
                manual_cases=['qualified raw sentinel carry without Floor raw copy',
                              'quiet current mean sentinel carry without inheritance',
                              'selected-screen reference closure',
                              'unmarked ordinary byte identity', 'safe-domain exclusions',
                              'malformed certificate payload', 'poisoned RR transition'])


def _model(floor):
    result = getattr(floor, '_floor_model', None)
    if result is None:
        raise RuntimeError('Actual Floor-model UAV readback is required')
    return np.asarray(result)


def _tags(model):
    return np.all(model[..., :3] == TAG, axis=-1)


def _projections(model):
    return np.all(model[..., :3] == PROJECTION_TAG, axis=-1)


def _safe_fp16_rgb(value):
    """Only the declared input-storage contract; no classifier approximation."""
    return np.clip(np.asarray(value[..., :3], np.float32), 0., 65504.).astype(np.float16).astype(np.float32)


def _untag(model):
    result = np.asarray(model).copy()
    result[_tags(result), :3] = ZERO_SLOPE
    return result


def _unmark(model):
    result = _untag(model)
    result[_projections(result), :3] = ZERO_SLOPE
    return result


def _patch_ulp(raw):
    """Maximum FP16 spacing in a complete 5x5 stored-radiance footprint."""
    stored = _safe_fp16_rgb(raw).astype(np.float64)
    exponent = np.maximum(np.floor(np.log2(np.maximum(stored, 2.**-14))) - 10, -24)
    spacing = np.exp2(exponent)
    padded = np.pad(spacing, ((2, 2), (2, 2), (0, 0)), mode='edge')
    result = np.zeros_like(spacing)
    h, w = spacing.shape[:2]
    for yy in range(5):
        for xx in range(5):
            result = np.maximum(result, padded[yy:yy+h, xx:xx+w])
    return result


def _roi(shape, margin=4):
    result = np.zeros(shape[:2], bool)
    result[margin:-margin, margin:-margin] = True
    return result


def _seed(frame, directory):
    h, w = frame.raw.shape[:2]
    cb = dict(InvProjMatrix=np.eye(4).ravel(), RenderSize=[w, h, 1 / w, 1 / h],
              NearPlane=.1, FarPlane=1000, Flags=1, FloorEnabled=1)
    return t.dispatch('FSRDFloorSeed', cb,
                      [frame.raw, frame.normals, frame.depth, frame.depth, frame.albedo],
                      [10, 41, 10, 10], (w, h), directory=directory)


def _seed_pair(frame, directory, control):
    active, old = _seed(frame, directory), _seed(frame, control)
    tag = _tags(_model(active[0]))
    projected = _projections(_model(active[0]))
    partial = ((np.any(_model(active[0])[..., :3] == TAG, axis=-1) & ~tag)
               | (np.any(_model(active[0])[..., :3] == PROJECTION_TAG, axis=-1) & ~projected))
    t.check(frame.name + ': exact complete RGB certificate', not partial.any(),
            partial_certificate_pixels=int(partial.sum()))
    t.check(frame.name + ': control disables both new Seed producer classes',
            not _tags(_model(old[0])).any() and not _projections(_model(old[0])).any())
    t.check(frame.name + ': Seed retains unprojected base, all linear depth and guide',
            np.array_equal(active[0][~projected], old[0][~projected])
            and np.array_equal(active[0][..., 3], old[0][..., 3])
            and np.array_equal(active[1], old[1]) and np.array_equal(active[2], old[2]),
            projected_pixels=int(projected.sum()))
    t.check(frame.name + ': Seed reference alpha remains C19 exact',
            np.array_equal(active[3][..., 3], old[3][..., 3]))
    t.check(frame.name + ': all Seed reference RGB remain producer-disabled exact before selection',
            np.array_equal(active[3][..., :3], old[3][..., :3]),
            tagged_pixels=int(tag.sum()))
    raw_stored = _safe_fp16_rgb(frame.raw)
    t.check(frame.name + ': Seed changes only zero-slope RGB attestation',
            np.array_equal(_unmark(_model(active[0])), _model(old[0])),
            tagged_pixels=int(tag.sum()))
    valid = (np.isfinite(active[3]).all(axis=-1) & (active[3][..., 3] >= 0)
             & (_model(active[0])[..., 3] >= .5))
    # Only final conversion stores may restore qualified raw. Noise/impulse
    # rejection and zero-slope/surface coherence are tested independently,
    # not reproduced in a CPU classifier or fed back through Seed reference.
    t.check(frame.name + ': attestation requires valid alpha and model metadata',
            np.all(~tag | valid), invalid_tag_pixels=int((tag & ~valid).sum()))
    maximum_ulp_error = 0.
    if projected.any():
        difference = np.abs(active[0][projected, :3] - raw_stored[projected])
        maximum_ulp_error = float(np.max(difference / _patch_ulp(frame.raw)[projected]))
    interior = _roi(frame.raw.shape, 2)
    t.check(frame.name + ': quiet local mean has finite positive independent query support',
            np.all(~projected | (interior & valid))
            and np.isfinite(active[0][projected]).all()
            and np.all(active[0][projected, :3] >= 0.)
            and maximum_ulp_error <= PROJECTION_ULP_LIMIT,
            projected_pixels=int(projected.sum()), maximum_query_difference_patch_ulp=maximum_ulp_error)
    return active, old


def _floor_pair(frame, active_seed, old_seed, steps, directory, control, label):
    h, w = frame.raw.shape[:2]
    active, old = active_seed[0], old_seed[0]
    initial = _tags(_model(active))
    initial_projection = _projections(_model(active))
    for step in steps:
        cb = dict(DstTexSize=[w, h, 1 / w, 1 / h], StepSize=step)
        active = t.dispatch('FSRDFloor', cb,
                            [active, active_seed[1], active_seed[2], frame.albedo, active_seed[3]],
                            [10], (w, h), directory=directory)[0]
        old = t.dispatch('FSRDFloor', cb,
                         [old, old_seed[1], old_seed[2], frame.albedo, old_seed[3]],
                         [10], (w, h), directory=control)[0]
        model = _model(active)
        if not initial_projection.any():
            t.check(f'{frame.name}: {label} step{step} retains control colour and confidence without projection',
                    np.array_equal(active, old) and np.array_equal(model[..., 3], _model(old)[..., 3])
                    and np.array_equal(_untag(model), _model(old)))
        else:
            t.check(f'{frame.name}: {label} step{step} retains the exact initial projected mean and model',
                    np.array_equal(active[initial_projection], active_seed[0][initial_projection])
                    and np.array_equal(model[initial_projection], _model(active_seed[0])[initial_projection]))
        t.check(f'{frame.name}: {label} step{step} carries only each centre certificate class',
                np.array_equal(_tags(model), initial)
                and np.array_equal(_projections(model), initial_projection),
                tagged_pixels=int(_tags(model).sum()),
                introduced_tags=int((_tags(model) & ~initial).sum()),
                lost_tags=int((initial & ~_tags(model)).sum()),
                projected_pixels=int(_projections(model).sum()),
                introduced_projection=int((_projections(model) & ~initial_projection).sum()),
                lost_projection=int((initial_projection & ~_projections(model)).sum()))
    return active, old


def _convert(frame, floor, reference, directory, model=None, **kwargs):
    h, w = frame.raw.shape[:2]
    resources = dict(kwargs.pop('resources', {}))
    if model is not None:
        resources[17] = model
    return c.convert(frame.raw, kwargs.pop('diff', frame.albedo),
                     kwargs.pop('spec', t.rgba(w, h, (.04, .04, .04))),
                     floor=floor, reference=reference, depth=frame.depth, normals=frame.normals,
                     directory=directory, resources=resources,
                     output_formats=c.CONV_FORMATS + [10, 10], **kwargs)


def _packed_equal(active, control, mask):
    # Compare every public channel, including hit distance, route and detail validity.
    return all(np.array_equal(a[mask], b[mask]) for a, b in zip(active, control))


def _packed_differences(active, control, mask, exposure):
    """Retain actual GPU pair differences; never estimate the control in Python."""
    differences = {}
    yy, xx = np.nonzero(mask)
    for slot, (observed, expected) in enumerate(zip(active, control)):
        delta = np.abs(observed[mask].astype(np.float64) - expected[mask].astype(np.float64))
        if not np.any(delta):
            continue
        pixel, channel = np.unravel_index(delta.argmax(), delta.shape)
        differences[str(slot)] = dict(
            differing_components=int(np.count_nonzero(delta)),
            channel_differing_counts=np.count_nonzero(delta, axis=0).tolist(),
            channel_maximum_absolute=delta.max(axis=0).tolist(),
            channel_maximum_normalized=(delta.max(axis=0) / exposure).tolist(),
            worst_pixel_yxc=[int(yy[pixel]), int(xx[pixel]), int(channel)],
            active_rgba=observed[yy[pixel], xx[pixel]].tolist(),
            control_rgba=expected[yy[pixel], xx[pixel]].tolist())
    return differences


def _rounding_fraction(observed, expected):
    expected = np.asarray(expected, np.float64)
    return float(np.max(np.abs(np.asarray(observed, np.float64) - expected) /
                        (BOUNDS['identity_relative'] * np.abs(expected)
                         + BOUNDS['identity_absolute'])))


def _rgb_metrics(result, truth, exposure, mask):
    observed = np.asarray(result, np.float64)[mask, :3] / exposure
    target = np.asarray(truth, np.float64)[mask, :3] / exposure
    error = observed - target
    centered = target - target.mean(axis=0)
    variance = np.sum(centered**2, axis=0)
    gain = np.sum(centered * (observed - observed.mean(axis=0)), axis=0) / variance
    return dict(channel_rmse=np.sqrt(np.mean(error**2, axis=0)).tolist(),
                channel_bias=np.abs(error.mean(axis=0)).tolist(),
                channel_peak=np.max(np.abs(error), axis=0).tolist(), channel_gain=gain.tolist())


def _packing_contract(frame, floor, old_floor, reference, old_reference,
                      directory, control, label):
    packed = _convert(frame, floor, reference, directory)
    untagged = _convert(frame, floor, reference, directory, model=_unmark(_model(floor)))
    old = _convert(frame, old_floor, old_reference, control)
    ordinary = packed[3][..., 3] == 0
    selected = np.abs(packed[3][..., 3] - 1 / 3) < .01
    tags = _tags(_model(floor))
    projected = _projections(_model(floor))
    # These natural fixtures have full modulation, known valid albedos, no title
    # routing/emission and valid model/reference fields. V2 also trusts a Seed
    # attestation on a safe ordinary lane without changing its material type.
    protected = tags
    native_slots = (0, 1, 2, 3, 4, 5, 8, 9)
    t.check(f'{frame.name}: {label} certificate classes preserve current native submissions and guides',
            all(np.array_equal(packed[index], untagged[index]) for index in native_slots)
            and np.array_equal(packed[7][..., 3], untagged[7][..., 3]),
            gpu_pair_differences={slot: difference for slot, difference in
                _packed_differences(packed, untagged, np.ones(tags.shape, bool), frame.exposure).items()
                if int(slot) in native_slots})
    unmarked_ordinary = ordinary & ~tags
    t.check(f'{frame.name}: {label} unprotected lanes remain byte exact against current unmarked model',
            _packed_equal(packed, untagged, ~tags),
            ordinary_pixels=int(ordinary.sum()), unmarked_ordinary_pixels=int(unmarked_ordinary.sum()),
            marked_ordinary_pixels=int((ordinary & tags).sum()),
            marked_selected_screen_pixels=int((selected & tags).sum()),
            gpu_pair_differences=_packed_differences(packed, untagged, ~tags, frame.exposure))
    unaffected = ~protected
    if not projected.any():
        t.check(f'{frame.name}: {label} no-projection native submissions remain exact against producer-disabled control',
                all(np.array_equal(packed[index], old[index]) for index in native_slots),
                gpu_pair_differences={slot: difference for slot, difference in
                    _packed_differences(packed, old, np.ones(tags.shape, bool), frame.exposure).items()
                    if int(slot) in native_slots})
        t.check(f'{frame.name}: {label} no-projection unprotected pixels remain byte exact against control',
                _packed_equal(packed, old, unaffected), unaffected_pixels=int(unaffected.sum()),
                gpu_pair_differences=_packed_differences(packed, old, unaffected, frame.exposure))
    raw_stored = _safe_fp16_rgb(frame.raw)
    t.check(f'{frame.name}: {label} protected qualified raw reaches authoritative Skip exactly',
            np.array_equal(packed[6][protected, :3], raw_stored[protected])
            and np.all(packed[6][protected, 3] == -1.),
            protected_pixels=int(protected.sum()))
    t.check(f'{frame.name}: {label} packed reference preserves validity and unprotected current RGB',
            np.array_equal(packed[7][..., 3], untagged[7][..., 3])
            and np.array_equal(packed[7][~protected, :3], reference[~protected, :3]))
    t.check(f'{frame.name}: {label} only protected packed reference RGB selects qualified raw after native calculations',
            np.array_equal(packed[7][protected, :3], raw_stored[protected]))
    if projected.any():
        t.check(f'{frame.name}: {label} quiet current mean is not an authoritative raw bypass',
                not np.any(packed[6][projected, 3] == -1.), projected_pixels=int(projected.sum()))
    return packed, protected, old, untagged


def _clean_contract(frame, active_seed, old_seed, directory, control, records):
    roi = _roi(frame.raw.shape)
    tags = _tags(_model(active_seed[0]))
    projected = _projections(_model(active_seed[0]))
    tag_count = int((tags & roi).sum())
    if frame.requires_certificate:
        _producer_check(frame.name + ': resolved RGB lighting has meaningful positive certificate coverage',
                tag_count >= BOUNDS['clean_tag_min_pixels'] and
                tag_count / int(roi.sum()) >= BOUNDS['clean_tag_min_fraction'],
                interior_tagged_pixels=tag_count, interior_pixels=int(roi.sum()))
    if frame.requires_projection:
        projected_count = int((projected & roi).sum())
        _producer_check(frame.name + ': analytic polynomial has meaningful local projection coverage',
                projected_count >= BOUNDS['clean_tag_min_pixels'] and
                projected_count / int(roi.sum()) >= BOUNDS['clean_tag_min_fraction'],
                interior_projected_pixels=projected_count, interior_pixels=int(roi.sum()))
    for label, steps in (('full', FULL), ('fast', FAST)):
        floor, old = _floor_pair(frame, active_seed, old_seed, steps, directory, control, label)
        packed, protected, old_packed, untagged_packed = _packing_contract(
            frame, floor, old, active_seed[3], old_seed[3], directory, control, label)
        result = c.compose(packed, directory=directory, depth=frame.depth, detail=1)
        metrics = _rgb_metrics(result, frame.truth, frame.exposure, roi)
        passed = (max(metrics['channel_rmse']) <= BOUNDS['clean_channel_rmse'] and
                  max(metrics['channel_bias']) <= BOUNDS['clean_channel_bias'] and
                  max(metrics['channel_peak']) <= BOUNDS['clean_channel_peak'] and
                  min(metrics['channel_gain']) >= BOUNDS['clean_gain_min'] and
                  max(metrics['channel_gain']) <= BOUNDS['clean_gain_max'])
        _producer_check(f'{frame.name}: {label} final composition retains analytic RGB lighting',
                passed, **metrics)
        if projected.any():
            identity = c.compose(packed, directory=directory, depth=frame.depth, detail=0.)
            query_error = np.abs(identity[projected, :3] - _safe_fp16_rgb(frame.raw)[projected])
            maximum_query = float(np.max(query_error / _patch_ulp(frame.raw)[projected]))
            t.check(f'{frame.name}: {label} projected native identity closes within independent query uncertainty',
                    maximum_query <= PROJECTION_ULP_LIMIT,
                    maximum_semantic_source_difference_patch_ulp=maximum_query,
                    projected_pixels=int(projected.sum()))
        stage_metrics = {name: _rgb_metrics(value, frame.truth, frame.exposure, roi)
                         for name, value in (('raw', frame.raw), ('reference', active_seed[3]),
                                             ('floor', floor), ('skip', packed[6]), ('final', result))}
        capture = None
        positive_failed = frame.requires_certificate and (
            tag_count < BOUNDS['clean_tag_min_pixels'] or
            tag_count / int(roi.sum()) < BOUNDS['clean_tag_min_fraction'])
        positive_failed |= frame.requires_projection and (
            int((projected & roi).sum()) < BOUNDS['clean_tag_min_pixels'] or
            int((projected & roi).sum()) / int(roi.sum()) < BOUNDS['clean_tag_min_fraction'])
        if not passed or positive_failed:
            capture_path = t.OUT.parent / f'failure_capture_{len(records):03}_{label}.npz'
            np.savez_compressed(capture_path, raw=frame.raw, truth=frame.truth, albedo=frame.albedo,
                                depth=frame.depth, normals=frame.normals, seed=active_seed[0],
                                reference=active_seed[3], floor=floor, model=_model(floor),
                                native_specular=packed[0], native_diffuse=packed[1],
                                route=packed[3], skip=packed[6], packed_reference=packed[7],
                                control_skip=old_packed[6], untagged_current_skip=untagged_packed[6],
                                control_seed_reference=old_seed[3], control_packed_reference=old_packed[7],
                                control_native_specular=old_packed[0],
                                control_native_diffuse=old_packed[1], final=result)
            capture = str(capture_path)
        records.append(dict(name=frame.name, chain=label, tag_pixels=tag_count,
                            requires_positive_certificate=frame.requires_certificate,
                            requires_positive_projection=frame.requires_projection,
                            protected_pixels=int(protected.sum()),
                            projected_pixels=int(projected.sum()),
                            source_rgb=stage_metrics, failure_capture=capture, **metrics))


def _noise_contract(frame, active_seed, old_seed, directory, control):
    count = int(_tags(_model(active_seed[0])).sum())
    projection_count = int(_projections(_model(active_seed[0])).sum())
    t.check(frame.name + ': stochastic grain supplies zero lighting certificates',
            count == BOUNDS['noise_tag_count'] and projection_count == 0,
            tagged_pixels=count, local_projection_pixels=projection_count)
    floor, old = _floor_pair(frame, active_seed, old_seed, FULL, directory, control, 'full')
    packed, protected, _, _ = _packing_contract(frame, floor, old, active_seed[3], old_seed[3],
                                               directory, control, 'full')
    t.check(frame.name + ': grain cannot acquire a protected Skip bypass',
            not protected.any(), protected_pixels=int(protected.sum()))
    ordinary = packed[3][..., 3] == 0
    t.check(frame.name + ': grain has a meaningful ordinary control', int(ordinary.sum()) >= 16,
            ordinary_pixels=int(ordinary.sum()))


def _cluster_contract(frame, centers, channels, active_seed, old_seed, directory, control):
    tag_count = int((_tags(_model(active_seed[0])) & centers).sum())
    yy, xx = np.nonzero(centers)
    cc = channels[centers]
    reference_gap = ((frame.raw[yy, xx, cc] - active_seed[3][yy, xx, cc]) / frame.exposure)
    t.check(frame.name + ': both coloured impulse clusters reject current-reference attestation',
            tag_count == 0 and not _projections(_model(active_seed[0]))[centers].any()
            and float(reference_gap.min()) >= BOUNDS['cluster_reference_rejection'],
            tagged_cluster_pixels=tag_count, minimum_reference_rejection=float(reference_gap.min()))
    for label, steps in (('full', FULL), ('fast', FAST)):
        floor, old = _floor_pair(frame, active_seed, old_seed, steps, directory, control, label)
        packed, protected, _, _ = _packing_contract(frame, floor, old, active_seed[3], old_seed[3],
                                                   directory, control, label)
        skip_gap = (frame.raw[yy, xx, cc] - packed[6][yy, xx, cc]) / frame.exposure
        t.check(f'{frame.name}: {label} coloured impulses cannot copy into protected Skip',
                not protected[centers].any() and float(skip_gap.min()) >= BOUNDS['cluster_skip_rejection'],
                protected_cluster_pixels=int(protected[centers].sum()),
                minimum_skip_rejection=float(skip_gap.min()))


def _boundary_contract(frame, boundary, left, right, active_seed, old_seed, directory, control):
    tag = _tags(_model(active_seed[0]))
    projected = _projections(_model(active_seed[0]))
    t.check(frame.name + ': complete coherence stencil cannot cross a surface seam',
            int((tag & boundary).sum()) == BOUNDS['boundary_tag_count']
            and not projected[boundary].any(),
            seam_tag_pixels=int((tag & boundary).sum()),
            seam_projection_pixels=int((projected & boundary).sum()),
            coherent_side_tag_pixels=int((tag & left).sum()))
    if frame.requires_certificate:
        _producer_check(frame.name + ': resolved coherent side remains observable', int((tag & left).sum()) >= 16,
                coherent_side_tag_pixels=int((tag & left).sum()))
    t.check(frame.name + ': neighbouring coherent surface cannot attest grain',
            int((tag & right).sum()) == 0 and not projected[right].any(),
            grain_side_tag_pixels=int((tag & right).sum()),
            grain_side_projection_pixels=int((projected & right).sum()))
    _floor_pair(frame, active_seed, old_seed, FULL, directory, control, 'full')


def _declared_postclip_energy(frame, floor, reference, packed, directory):
    """Independent submitted-energy accounting; not a clean-light quality oracle.

    This fixture family has full modulation, positive roughness, finite normals,
    valid input albedos, and no routing/bias/emission/half signals. Capture actual
    material routing but derive the source from raw/Floor/model/reference and
    known production expressions. Never subtract the measured Skip or RR output.
    """
    compact = re.sub(r'\s+', '', (Path(directory) / 'FSRDInputConv.hlsl').read_text(encoding='utf-8'))
    required = (
        'constfloat3residualSource=lerp(rawColor,spatialFloor,sourceWeight);',
        'float3denoiserColor=(1.0f-biasWeight)*max(residualSource-spatialFloor,0.0f);',
        'constfloatmodelSourceWeight=ordinaryNoiseModel&&(any(materialSlope>0.0f)||planeConfidence>0.0f)&&detailReference.a>=0.0f?smoothstep(0.005f,0.025f,detailReference.a/max(GetLuminance(FloorRadiance(detailReference.rgb)),1e-5f)):0.0f;',
        'constfloat3sourceWeight=modelSourceWeight*max(all(materialSlope>0.0f)?1.0f:0.0f,planeConfidence);',
        'if(ordinaryNoiseModel&&detailReference.a>=0.0f&&planeConfidence==0.0f&&!any(materialSlope>0.0f)){constfloatclippingBias=0.15f*FloorClippingNoiseRatio(floorModel)*GetLuminance(floorColor.rgb);floorColor.rgb=max(floorColor.rgb-min(clippingBias,0.05f*floorColor.rgb),0.0f);}',
    )
    common = re.sub(r'\s+', '', (Path(directory) / 'FSRDPreprocessCommon.hlsli').read_text(encoding='utf-8'))
    model_source = re.sub(r'\s+', '', (Path(directory) / 'FSRDFloorModel.hlsli').read_text(encoding='utf-8'))
    model_expressions = (
        'if(model.a<0.5f)return0.0f;',
        'returnfloat3(model.x>-99.0f?exp2(model.x):0.0f,model.y>-99.0f?exp2(model.y):0.0f,model.z>-99.0f?exp2(model.z):0.0f);',
        'returnmodel.a>=2.0f?saturate(model.a-2.0f):0.0f;',
        'returnmodel.a<2.0f?max(model.a-1.0f,0.0f):0.0f;',
    )
    if (any(expression not in compact for expression in required)
            or any(expression not in model_source for expression in model_expressions)
            or 'returndot(color,float3(0.2126f,0.7152f,0.0722f));' not in common):
        raise ValueError('Unknown declared sparse consumer-source arithmetic')
    if not np.all(np.isfinite(frame.albedo)) or np.any(frame.albedo[..., :3] <= 0) or np.any(frame.albedo[..., :3] + .04 > 1):
        raise ValueError('Source oracle only covers this full-safe fixture domain')
    raw = _safe_fp16_rgb(frame.raw).astype(np.float64)
    spatial = np.clip(np.asarray(floor[..., :3], np.float64), 0., 65500.)
    model = _model(floor).astype(np.float64)
    selected = np.abs(packed[3][..., 3] - 1 / 3) < .01
    ordinary = packed[3][..., 3] == 0
    if not np.isfinite(model).all() or not np.all(selected | ordinary):
        raise ValueError('Source oracle requires finite models and ordinary/selected routing')
    spatial[selected] = 0.
    slope = (model[..., :3] > -99.) & (model[..., 3:4] >= .5)
    plane = np.where(model[..., 3] >= 2., np.clip(model[..., 3] - 2., 0., 1.), 0.)
    ref = np.clip(np.asarray(reference[..., :3], np.float64), 0., 65500.)
    ratio = reference[..., 3] / np.maximum(ref @ c.LUMA, 1e-5)
    signal = np.clip((ratio - .005) / .020, 0., 1.)
    signal = signal * signal * (3. - 2. * signal)
    eligible = ordinary & (model[..., 3] >= .5) & (reference[..., 3] >= 0)
    signal *= eligible & (slope.any(axis=-1) | (plane > 0))
    # One source decision for all channels (a partial-channel model keeps raw).
    weights = signal[..., None] * np.maximum(slope.all(axis=-1), plane)[..., None]
    submitted_source = raw * (1. - weights) + spatial * weights
    legacy = eligible & (plane == 0) & ~slope.any(axis=-1)
    bias = .15 * np.maximum(model[..., 3] - 1., 0.) * (spatial @ c.LUMA)
    bias = np.where(legacy[..., None], np.minimum(bias[..., None], .05 * spatial), 0.)
    # The declared split retains Floor on a negative residual, and removes only
    # this known clipping correction. That is distinct from an ideal clean truth.
    energy = np.maximum(submitted_source, spatial) - bias
    protected = packed[6][..., 3] == -1.
    energy[protected] = raw[protected]
    return energy, submitted_source, bias


def _sparse_contract(directory, control, output):
    """Seed-only causal A/B, with bounded actual consumer-identity witnesses.

    A supported background is independent of a bright query's source authority.
    The oracle uses that declared population and stored input truth, never a
    CPU replica of covariance/impulse classifiers or the current packed Skip.
    """
    source = re.sub(r'\s+', '', (Path(directory) / 'FSRDFloorSeed.hlsl').read_text(encoding='utf-8'))
    tapered = 'constfloatgeometryConfidence=1.0f-smoothstep(7.5f,9.0f,modelSupport);' in source
    if not tapered or 'base=max(base,sparsePedestal*permission);' not in source:
        raise ValueError('Unknown declared sparse geometry-support taper')
    records, ulp_bases, guide_bases = [], [], []
    frames = list(sparse_frames()) + list(sparse_adversarial_frames())
    for index, (frame, meta, kind) in enumerate(frames):
        seed, disabled = _seed(frame, directory), _seed(frame, control)
        cy, cx = meta['centre_yx']
        model, plain_model = _model(seed[0]), _model(disabled[0])
        base, old_base = seed[0][cy, cx, :3], disabled[0][cy, cx, :3]
        raw = _safe_fp16_rgb(frame.raw)
        tolerance = BOUNDS['identity_relative'] * np.maximum(old_base, raw[cy, cx]) + BOUNDS['identity_absolute']
        classes = lambda value: np.where(value[..., 3] >= 2., 2,
                                        np.where(value[..., 3] >= .5, 1, 0))
        t.check(frame.name + ': sparse uplift retains exact reference/sigma/depth/guide and model RGB permissions',
                np.array_equal(seed[3], disabled[3])
                and np.array_equal(seed[0][..., 3], disabled[0][..., 3])
                and np.array_equal(seed[1], disabled[1]) and np.array_equal(seed[2], disabled[2])
                and np.array_equal(model[..., :3], plain_model[..., :3])
                and np.array_equal(classes(model), classes(plain_model))
                and np.array_equal(model[classes(model) != 1, 3], plain_model[classes(model) != 1, 3]))
        t.check(frame.name + ': sparse uplift is finite, monotone and bounded by current/common light',
                np.isfinite(seed[0]).all() and np.all(seed[0][..., :3] >= disabled[0][..., :3])
                and np.all(base <= np.maximum(old_base, raw[cy, cx]) + tolerance),
                query_rgb=base.tolist(), disabled_rgb=old_base.tolist(),
                query_model=model[cy, cx].tolist(), disabled_model=plain_model[cy, cx].tolist())
        coords = np.asarray(meta['same_geometry_yx'])
        materials = frame.albedo[..., :3].astype(np.float16).astype(np.float64)
        population = raw[coords[:, 0], coords[:, 1]].astype(np.float64)
        lower = np.min(population / np.maximum(materials[coords[:, 0], coords[:, 1]], .02), axis=0) * materials[cy, cx]
        lower = np.minimum(lower, raw[cy, cx])
        # This declared binary-normal footprint has exact unit geometry weights.
        # C25 intentionally fades the lower anchor as weighted support reaches9.
        phase = np.clip((meta['same_geometry_count'] - 7.5) / 1.5, 0., 1.)
        geometry_confidence = 1. - phase * phase * (3. - 2. * phase)
        lower *= geometry_confidence
        unsupported = model[cy, cx, :3] <= -99.
        if kind in ('uplift', 'mixed', 'guide', 'cross'):
            permitted = np.ones(3, bool)
            if kind == 'mixed':
                permitted[0] = False
                t.check(frame.name + ': positive R is a genuine accepted-model control',
                        model[cy, cx, 0] > -99. and plain_model[cy, cx, 0] > -99.
                        and seed[0][cy, cx, 0] == disabled[0][cy, cx, 0])
            if kind == 'guide':
                permitted[1] = False
                t.check(frame.name + ': excluded dark/gain G stays exactly sparse-disabled',
                        unsupported[1] and base[1] == old_base[1])
            # A bright rejected background may already supply common-volume
            # light; its existing pedestal need not exhibit an additional lift.
            bright_common = kind == 'cross' and max(frame.raw[0, 0, :3]) > max(raw[cy, cx])
            t.check(frame.name + ': independent supported lower population remains without a new model',
                    np.all(unsupported[permitted]) and
                    np.all(base[permitted] + tolerance[permitted] >= lower[permitted])
                    and (bright_common or np.all(base[permitted] > old_base[permitted])),
                    minimum_population_rgb=lower.tolist(), positive_uplift_channels=(base > old_base).tolist())
        if kind == 'quiet':
            t.check(frame.name + ': quiet additive pedestal is a stored fixed point',
                    np.array_equal(base, raw[cy, cx]) and np.array_equal(base, old_base))
        if kind == 'cluster':
            t.check(frame.name + ': quiet supported minimum cannot add a bright-cluster uplift',
                    _rounding_fraction(old_base, np.full(3, 2.53125)) <= 1.
                    and _rounding_fraction(base, old_base) <= 1. and unsupported.all()
                    and model[cy, cx, 3] < 2. and not _tags(model)[cy, cx])
        if kind == 'guide_ulp':
            t.check(frame.name + ': guide gain boundary is bounded without requiring positive gain2 uplift',
                    np.all(old_base == 0.) and np.all(base <= raw[cy, cx] + tolerance)
                    and unsupported.all() and model[cy, cx, 3] < 2. and not _tags(model)[cy, cx])
            guide_bases.append(base.copy())
        if kind in ('insufficient', 'zero'):
            t.check(frame.name + ': unsupported or zero-population impulse grants no new pedestal',
                    np.array_equal(seed[0], disabled[0])
                    and (kind != 'zero' or np.all(base == 0.)))
        if kind in ('impulse', 'ulp', 'zero'):
            t.check(frame.name + ': positive centre cannot gain beta/plane/raw-source authority',
                    unsupported.all() and model[cy, cx, 3] < 2.
                    and not _tags(model)[cy, cx] and not _projections(model)[cy, cx]
                    and not np.array_equal(seed[3][cy, cx, :3], raw[cy, cx]))
            if kind == 'impulse':
                neighbours = population[:-1] if np.array_equal(coords[-1], [cy, cx]) else population[1:]
                t.check(frame.name + ': bright impulse retains only a supported background pedestal',
                        np.all(base <= neighbours.max(axis=0) + tolerance) and np.all(base > old_base))
            if kind == 'ulp':
                target = np.full(3, np.float16(.399902344), np.float32)
                t.check(frame.name + ': one-ULP query retains its known supported lower population',
                        _rounding_fraction(base, target) <= 1.)
                ulp_bases.append(base.copy())
        captured = dict(raw=frame.raw, truth=frame.truth, albedo=frame.albedo,
                        depth=frame.depth, normals=frame.normals, seed=seed[0],
                        reference=seed[3], model=model, disabled_seed=disabled[0],
                        disabled_reference=disabled[3], disabled_model=plain_model)
        closure_records = []
        # Representatives exercise both actual current/control consumers. This
        # is declared source accounting; clean RGB truth gates stay separate.
        if index in (0, 5, 8, 13, 14, 15, 16, 17, 18):
            for label, steps in (('full', FULL), ('fast', FAST)):
                h, w = frame.raw.shape[:2]
                for variant, initial, dispatch_dir in (('current', seed, directory),
                                                       ('sparse_disabled', disabled, control)):
                    floor = initial[0]
                    for step in steps:
                        floor = t.dispatch('FSRDFloor', dict(DstTexSize=[w, h, 1/w, 1/h], StepSize=step),
                            [floor, initial[1], initial[2], frame.albedo, initial[3]], [10],
                            (w, h), directory=dispatch_dir)[0]
                    packed = _convert(frame, floor, initial[3], dispatch_dir)
                    result = c.compose(packed, directory=dispatch_dir, depth=frame.depth, detail=0.)
                    energy, submitted_source, correction = _declared_postclip_energy(
                        frame, floor, initial[3], packed, dispatch_dir)
                    packed_energy = (packed[0][..., :3].astype(np.float64) * packed[4][..., :3] +
                                     packed[1][..., :3].astype(np.float64) * packed[5][..., :3] + packed[6][..., :3])
                    target = energy[cy, cx]
                    fraction = _rounding_fraction(result[cy, cx, :3], target)
                    packing_fraction = _rounding_fraction(packed_energy[cy, cx], target)
                    t.check(f'{frame.name}: {label} {variant} actual RR/Skip closes declared postclip source',
                            fraction <= 1. and packing_fraction <= 1.,
                            maximum_storage_tolerance_fraction=fraction,
                            packing_storage_tolerance_fraction=packing_fraction,
                            final_rgb=result[cy, cx, :3].tolist(), declared_energy=target.tolist(),
                            stored_raw_ideal_rgb=raw[cy, cx].tolist())
                    t.check(f'{frame.name}: {label} {variant} background pedestal never becomes authoritative raw Skip',
                            packed[6][cy, cx, 3] != -1. and not _tags(_model(floor))[cy, cx])
                    for name, value in (('floor', floor), ('floor_model', _model(floor)),
                                        ('native_specular', packed[0]), ('native_diffuse', packed[1]),
                                        ('specular_albedo', packed[4]), ('diffuse_albedo', packed[5]),
                                        ('route', packed[3]), ('skip', packed[6]),
                                        ('packed_reference', packed[7]), ('submitted_source', submitted_source),
                                        ('declared_correction', correction), ('declared_energy', energy),
                                        ('packed_energy', packed_energy), ('final', result)):
                        captured[label + '_' + variant + '_' + name] = value
                    closure_records.append(dict(chain=label, variant=variant,
                                                source_accounting_tolerance_fraction=fraction,
                                                packing_tolerance_fraction=packing_fraction,
                                                raw_ideal_difference_fraction=_rounding_fraction(result[cy, cx, :3], raw[cy, cx]),
                                                source_rgb=submitted_source[cy, cx].tolist(),
                                                correction_rgb=correction[cy, cx].tolist(), energy_rgb=target.tolist(),
                                                route=packed[3][cy, cx].tolist(), skip=packed[6][cy, cx].tolist()))
        path = output / f'sparse_capture_{index:02}.npz'
        np.savez_compressed(path, **captured)
        records.append(dict(name=frame.name, kind=kind, fixture=_identity(frame), metadata=meta,
                            query_base=base.tolist(), disabled_base=old_base.tolist(),
                            query_model=model[cy, cx].tolist(), disabled_model=plain_model[cy, cx].tolist(),
                            closure=closure_records, capture=str(path), capture_sha256=_hash(path)))
    t.check('one FP16 ULP cannot switch supported radiance into a zero Floor pedestal',
            len(ulp_bases) == 2 and _rounding_fraction(ulp_bases[0], ulp_bases[1]) <= 1.,
            query_base_pair=[value.tolist() for value in ulp_bases])
    signal_scale = np.full(3, np.float16(.399902), np.float32)
    allowance = BOUNDS['identity_relative'] * signal_scale + BOUNDS['identity_absolute']
    t.check('one FP16 guide ULP cannot produce a full supported-background flash at gain2',
            len(guide_bases) == 2 and np.all(np.abs(guide_bases[0] - guide_bases[1]) <= allowance),
            query_base_pair=[value.tolist() for value in guide_bases], allowed_change=allowance.tolist())
    return records


def _manual_carry(directory, control):
    w, h = 37, 29
    y, x = np.indices((h, w))
    base = c.rgba(_wave(w, h, .21, .43), .02)
    reference = base.copy()
    depth = np.full((h, w), 10., np.float32)
    guide = t.rgba(w, h, (0, 0, 0))
    albedo = t.rgba(w, h, (.48, .52, .44))
    marked = (x + 3 * y) % 7 == 0
    model = t.rgba(w, h, (ZERO_SLOPE,) * 3, 2.75)
    model[marked, :3] = TAG
    for label, steps in (('full', FULL), ('fast', FAST)):
        active, untagged, old = base, base, base
        active_model, plain_model = model, _untag(model)
        control_model = _untag(model)
        for step in steps:
            cb = dict(DstTexSize=[w, h, 1 / w, 1 / h], StepSize=step)
            active = t.dispatch('FSRDFloor', cb, [active, depth, guide, albedo, reference, active_model],
                                [10], (w, h), directory=directory)[0]
            untagged = t.dispatch('FSRDFloor', cb, [untagged, depth, guide, albedo, reference, plain_model],
                                  [10], (w, h), directory=directory)[0]
            old = t.dispatch('FSRDFloor', cb, [old, depth, guide, albedo, reference, control_model],
                             [10], (w, h), directory=control)[0]
            active_model, plain_model, control_model = _model(active), _model(untagged), _model(old)
            t.check(f'manual {label} step{step}: exact centre sentinel carry',
                    np.array_equal(_tags(active_model), marked)
                    and np.array_equal(_untag(active_model), plain_model)
                    and np.array_equal(plain_model, control_model),
                    expected_tag_pixels=int(marked.sum()), actual_tag_pixels=int(_tags(active_model).sum()))
            t.check(f'manual {label} step{step}: certificate retains filtered C19 colour',
                    np.array_equal(active, untagged) and np.array_equal(active, old))
        difference = float(np.max(np.abs(active[..., :3] - reference[..., :3])))
        t.check(f'manual {label}: filtered-colour witness is independent of a raw-copy path',
                difference > .005, maximum_filter_change=difference)

    # A forged local-mean marker exercises only its consumer protocol. It is not
    # evidence that this synthetic field passes the independent Seed classifier.
    # Sparse centres keep a distinct stored mean and model alpha through every
    # spatial step; an unmarked neighbour may read them but cannot inherit a tag.
    projection_model = t.rgba(w, h, (ZERO_SLOPE,) * 3, 2.75)
    projection_model[marked, :3] = PROJECTION_TAG
    stored_base = base.astype(np.float16).astype(np.float32)
    stored_model = projection_model.astype(np.float16).astype(np.float32)
    for label, steps in (('full', FULL), ('fast', FAST)):
        current, current_model = base, projection_model
        for step in steps:
            cb = dict(DstTexSize=[w, h, 1 / w, 1 / h], StepSize=step)
            current = t.dispatch('FSRDFloor', cb,
                [current, depth, guide, albedo, reference, current_model], [10],
                (w, h), directory=directory)[0]
            current_model = _model(current)
            t.check(f'manual quiet mean {label} step{step}: centre RGBA and model are exact without tag inheritance',
                    np.array_equal(current[marked], stored_base[marked])
                    and np.array_equal(current_model[marked], stored_model[marked])
                    and np.array_equal(_projections(current_model), marked)
                    and not _tags(current_model).any(),
                    expected_projection_pixels=int(marked.sum()),
                    actual_projection_pixels=int(_projections(current_model).sum()))


def _composition_aliases(directory, output):
    """Execute actual variant DXIL without modifying the shared runner or shaders.

    Variants have the same production CB/resource ABI as FSRDOutputComp. The
    existing helper dispatch schema needs its basename; alias only the binary in
    this run's output, retaining the exact common declaration for CB packing.
    Record both the actual variant source and selected DXIL hash for provenance.
    """
    result, records = {}, {}
    for variant in COMPOSITION_VARIANTS:
        if variant == 'FSRDOutputComp':
            result[variant] = directory
        else:
            target = output / ('abi_alias_' + variant)
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(directory / 'FSRDOutputComp.hlsl', target / 'FSRDOutputComp.hlsl')
            for include in directory.glob('*.hlsli'):
                shutil.copyfile(include, target / include.name)
            shutil.copyfile(directory / (variant + '_Shader.cso'),
                            target / 'FSRDOutputComp_Shader.cso')
            result[variant] = target
        records[variant] = dict(semantic_source=str(directory / (variant + '.hlsl')),
                                source_sha256=_hash(directory / (variant + '.hlsl')),
                                dxil_sha256=_hash(directory / (variant + '_Shader.cso')),
                                dispatch_directory=str(result[variant]))
    return result, records


def _manual_conversion(directory, control, stale_rr_guard, composition_dirs):
    w, h = 37, 29
    rgb = np.broadcast_to([.32, .36, .40], (h, w, 3)).astype(np.float32)
    frame = _frame('manual selected screen', rgb)
    floor = t.rgba(w, h, (.06, .08, .09), .01)
    reference = t.rgba(w, h, (.28, .30, .35), .01)
    model = t.rgba(w, h, (TAG,) * 3, 1.25)
    untagged = _untag(model)
    roi = _roi(frame.raw.shape, 3)
    zero_roughness = np.zeros((h, w), np.float32)
    flags = c.conversion_cb(w, h, floor=True)['Flags']

    def convert(which, **kwargs):
        return _convert(frame, kwargs.pop('floor', floor), kwargs.pop('reference', reference),
                        kwargs.pop('directory', directory), model=which,
                        roughness=kwargs.pop('roughness', zero_roughness), **kwargs)

    packed = convert(model)
    plain = convert(untagged)
    old = convert(untagged, directory=control)
    selected = np.abs(packed[3][..., 3] - 1 / 3) < .01
    t.check('manual safe tag protects only an already selected screen',
            selected[roi].all() and np.array_equal(packed[3], plain[3]),
            selected_pixels=int(selected.sum()), scored_pixels=int(roi.sum()))
    raw_source = _safe_fp16_rgb(frame.raw)
    t.check('manual raw certificate uses current raw independent of distinct passed reference and Floor',
            np.array_equal(packed[6][roi, :3], raw_source[roi])
            and np.array_equal(packed[7][roi, :3], raw_source[roi])
            and not np.array_equal(raw_source[roi], reference[roi, :3]))
    t.check('manual protected screen keeps all C19 native submissions and guides byte exact',
            all(np.array_equal(packed[index], old[index]) for index in (0, 1, 2, 3, 4, 5, 8, 9))
            and np.array_equal(packed[7][..., 3], old[7][..., 3]))
    t.check('warm native-history witness has meaningful positive submitted lobes',
            np.count_nonzero(packed[0][roi, :3]) > 0 and np.count_nonzero(packed[1][roi, :3]) > 0,
            positive_specular_components=int(np.count_nonzero(packed[0][roi, :3])),
            positive_diffuse_components=int(np.count_nonzero(packed[1][roi, :3])))

    if stale_rr_guard == 'required':
        t.check('manual protected screen writes the exact stale-RR transition guard',
                np.all(packed[6][roi, 3] == -1.), guarded_pixels=int((packed[6][..., 3] == -1).sum()))
        poisons = (
            ('identity warm lobes', packed[0], packed[1]),
            ('stale bright chromatic lobes', t.rgba(w, h, (1.7, .8, 2.3), 10.),
             t.rgba(w, h, (.9, 2.1, 1.2), 10.)),
            ('stale dim complementary lobes', t.rgba(w, h, (.001, .07, .002), 10.),
             t.rgba(w, h, (.09, .001, .08), 10.)),
        )
        for variant, composition_directory in composition_dirs.items():
            for detail in (0., .35, 1.):
                for poison_name, poison_spec, poison_diff in poisons:
                    result = c.compose(packed, spec=poison_spec, diff=poison_diff,
                                       directory=composition_directory, detail=detail)
                    fraction = _rounding_fraction(result[roi, :3], frame.raw[roi, :3])
                    t.check(f'{variant}: protected {poison_name} consumes qualified raw once detail{detail}',
                            fraction <= 1., maximum_storage_tolerance_fraction=fraction)
        # Removing protection must immediately restore the ordinary RR response.
        for variant, composition_directory in composition_dirs.items():
            plain_poison = c.compose(plain, spec=poisons[1][1], diff=poisons[1][2],
                                     directory=composition_directory, detail=0)
            response = float(np.max(np.abs(plain_poison[roi, :3] - raw_source[roi])))
            t.check(variant + ': stale-RR witness has a positive unprotected control', response > .25,
                    maximum_unprotected_response=response)
            equivalent = list(packed)
            equivalent[6] = packed[6].copy()
            equivalent[6][..., 3] = equivalent[6][..., :3] @ c.LUMA
            result = c.compose(equivalent, spec=poisons[1][1], diff=poisons[1][2],
                               directory=composition_directory, detail=0)
            response = float(np.max(np.abs(result[roi, :3] - raw_source[roi])))
            t.check(variant + ': only the exact negative unit flag rejects stale RR', response > .25,
                    maximum_unguarded_response=response)
    else:
        t.check('pending stale-RR interface cannot claim a complete lighting contract', False,
                pending_interface='Skip.A=-1 and protected Reconstruct')

    excluded = [
        ('Floor disabled', dict(overrides={'Flags': flags & ~(1 << 7)})),
        ('recovery selection disabled', dict(overrides={'RecoveryMask': 0})),
        ('partial diffuse modulation', dict(overrides={'DiffuseAlbedoModulation': .5})),
        ('partial specular modulation', dict(overrides={'SpecularAlbedoDemodulation': .5})),
        ('half diffuse layout', dict(overrides={'Flags': flags | (1 << 24)})),
        ('half specular layout', dict(overrides={'Flags': flags | (1 << 25)})),
        ('unsupported albedo flag', dict(overrides={'Flags': flags | (1 << 28)})),
        ('fractional bias mask', dict(overrides={'Flags': flags | (1 << 15)},
                                     resources={8: np.full((h, w), .35, np.float32)})),
        ('routed responsivity', dict(overrides={'Flags': flags | (1 << 13),
                                              'ResponsivityTrustThreshold': .5},
                                    resources={15: np.zeros((h, w), np.float32)})),
        ('inverted routed responsivity', dict(overrides={'Flags': flags | (1 << 13),
                                              'ResponsivityTrustThreshold': .5, 'ResponsivityInvert': 1},
                                             resources={15: np.ones((h, w), np.float32)})),
        ('unknown diffuse albedo', dict(diff=t.rgba(w, h, (0, 0, 0)))),
        ('predominantly specular albedo', dict(diff=t.rgba(w, h, (.02,) * 3),
                                              spec=t.rgba(w, h, (.7,) * 3))),
        ('original albedo overshoot', dict(diff=t.rgba(w, h, (.8,) * 3),
                                          spec=t.rgba(w, h, (.4,) * 3))),
        ('emissive reinterpretation', dict(diff=t.rgba(w, h, (2.,) * 3),
                                          spec=t.rgba(w, h, (2.,) * 3))),
        ('negative reference validity', dict(reference=t.rgba(w, h, (.28, .30, .35), -1.))),
        ('nonfinite reference uncertainty', dict(reference=t.rgba(w, h, (.28, .30, .35), np.nan))),
        ('invalid surface normal', dict()),
    ]
    for name, arguments in excluded:
        saved_normals = frame.normals
        if name == 'invalid surface normal':
            frame.normals = t.rgba(w, h, (0, 0, 0))
        try:
            active = convert(model, **arguments)
            disabled = convert(untagged, **arguments)
            old = convert(untagged, directory=control, **arguments)
            t.check(name + ': forged tag cannot protect excluded content',
                    _packed_equal(active, disabled, roi) and _packed_equal(active, old, roi)
                    and not np.any(active[6][roi, 3] == -1.))
            active_result = c.compose(active, directory=directory, detail=0)
            plain_result = c.compose(disabled, directory=directory, detail=0)
            t.check(name + ': identity composition remains byte exact with an untagged control',
                    np.array_equal(active_result[roi], plain_result[roi]))
            # Half-layout identity includes the matching second signal, exactly as
            # production sums two denoised halves. Partial modulation uses its own
            # declared multiplier; no packed-current residual is subtracted.
            cb = c.conversion_cb(w, h, floor=True, **arguments.get('overrides', {}))
            identity_spec = active[0].copy()
            identity_diff = active[1].copy()
            identity_spec[..., :3] *= 2 if int(cb['Flags']) & (1 << 25) else 1
            identity_diff[..., :3] *= 2 if int(cb['Flags']) & (1 << 24) else 1
            identity_result = c.compose(active, spec=identity_spec, diff=identity_diff,
                                        spec_strength=cb['SpecularAlbedoDemodulation'],
                                        diff_strength=cb['DiffuseAlbedoModulation'],
                                        directory=directory, detail=0)
            fraction = _rounding_fraction(identity_result[roi, :3], frame.raw[roi, :3])
            t.check(name + ': complete identity signals retain analytic input energy', fraction <= 1.,
                    maximum_storage_tolerance_fraction=fraction)
        finally:
            frame.normals = saved_normals

    # Scalar/partial matches must not masquerade as the exact three-channel tag.
    for rgb in ((TAG, ZERO_SLOPE, TAG), (-100.5,) * 3, (-102.,) * 3):
        malformed = t.rgba(w, h, rgb, 1.25)
        malformed_packed = convert(malformed)
        t.check('malformed certificate ' + str(rgb) + ' cannot protect a screen',
                _packed_equal(malformed_packed, plain, roi))
    invalid_model = t.rgba(w, h, (TAG,) * 3, 0.)
    invalid_plain = t.rgba(w, h, (ZERO_SLOPE,) * 3, 0.)
    t.check('uninitialised model cannot attest coherent lighting',
            _packed_equal(convert(invalid_model), convert(invalid_plain), roi))

    # The handover selection itself must not be widened by the certificate.
    y, x = np.indices((h, w))
    material = frame.albedo.copy()
    for channel in range(3):
        material[..., channel] = .40 + .12 * np.sin(.83 * x + .71 * y + channel)
    ordinary_raw = material.copy()
    ordinary_raw[..., :3] = .7 * material[..., :3] + [.06, .04, .08]
    ordinary = Frame('manual ordinary material', ordinary_raw, ordinary_raw.copy(), material,
                     frame.depth, frame.normals, 1.)
    reference_ordinary = ordinary_raw.copy()
    reference_ordinary[..., 3] = 0.
    no_noise_tag = t.rgba(w, h, (TAG,) * 3, 1.)
    no_noise_plain = _untag(no_noise_tag)
    active = _convert(ordinary, floor, reference_ordinary, directory, model=no_noise_tag)
    disabled = _convert(ordinary, floor, reference_ordinary, directory, model=no_noise_plain)
    old = _convert(ordinary, floor, reference_ordinary, control, model=no_noise_plain)
    ordinary_mask = active[3][..., 3] == 0
    t.check('manually attested ordinary material remains an actual q0 surface',
            ordinary_mask[roi].all(), ordinary_pixels=int(ordinary_mask.sum()))
    t.check('unmarked ordinary material conversion remains byte exact against C19',
            _packed_equal(disabled, old, roi))
    t.check('trusted ordinary attestation keeps native submissions and material type unchanged',
            all(np.array_equal(active[index][roi], old[index][roi])
                for index in (0, 1, 2, 3, 4, 5, 7, 8, 9)))
    t.check('trusted ordinary attestation consumes qualified raw after unchanged native calculations',
            np.array_equal(active[6][roi, :3], _safe_fp16_rgb(ordinary.raw)[roi])
            and np.all(active[6][roi, 3] == -1.))
    active_seed, _ = _seed_pair(ordinary, directory, control)
    t.check('varying material guide does not generate a coherent-lighting Seed certificate',
            not _tags(_model(active_seed[0])).any(),
            tagged_pixels=int(_tags(_model(active_seed[0])).sum()))
    result = c.compose(active, directory=directory, detail=0)
    fraction = _rounding_fraction(result[roi, :3], ordinary.truth[roi, :3])
    t.check('ordinary material identity energy closes independently of the certificate', fraction <= 1.,
            maximum_storage_tolerance_fraction=fraction)
    for variant, composition_directory in composition_dirs.items():
        if variant == 'FSRDOutputCompTileAnchor':
            # No handover tile exists in this all-ordinary scene. TileAnchor
            # returns without writing; its output belongs to TileLight in the
            # paired shared-UAV driver. An independent fresh output is undefined.
            continue
        result = c.compose(active, spec=t.rgba(w, h, (1.7, .8, 2.3), 10.),
                           diff=t.rgba(w, h, (.9, 2.1, 1.2), 10.),
                           directory=composition_directory, detail=1.)
        fraction = _rounding_fraction(result[roi, :3], ordinary.truth[roi, :3])
        t.check(variant + ': trusted ordinary attestation rejects stale native input', fraction <= 1.,
                maximum_storage_tolerance_fraction=fraction)


def run(directory=None, output=None, control_directory=None, *, stale_rr_guard='required'):
    """Fresh normal validation run; an explicit old control is diagnostic only.

    Preparation compiles only the macro-disabled Seed. All actual GPU work is
    owned by this run's newly built private runner, never a cached result.
    """
    source_directory = Path(directory or t.PRE).resolve()
    global RETIRED_PRODUCERS
    RETIRED_PRODUCERS = _producers_retired((source_directory / 'FSRDFloorSeed.hlsl').read_text(encoding='utf-8'))
    source_control = Path(control_directory).resolve() if control_directory is not None else None
    output = Path(output or t.OUT / 'floor_lighting_contract').resolve()
    if stale_rr_guard not in ('required', 'pending'):
        raise ValueError('Unknown stale-RR contract state')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Lighting output must be new or empty; prior evidence is never overwritten')
    if source_control is not None and source_directory == source_control:
        raise ValueError('Candidate and explicit diagnostic control must differ')
    output.mkdir(parents=True, exist_ok=True)
    dependency_start = _dependency_identity()
    plan = description()
    saved = (t.OUT, t.runner, t.checks, t.timings, t.counter)
    t.checks, t.timings, t.counter = [], [], 0
    records, error = [], None
    candidate_id = control_id = sparse_id = source_files = control_source_files = None
    directory = output / 'snapshots' / 'candidate' / 'precompile'
    control_directory = output / 'snapshots' / 'control' / 'precompile'
    sparse_directory = output / 'snapshots' / 'sparse_control' / 'precompile'
    report = dict(purpose=__doc__, scope='independent GPU contracts; no native AMD quality claim',
                  certificate_interface=CERTIFICATE_INTERFACE,
                  accepted=False, stale_rr_guard=stale_rr_guard, plan=plan,
                  dependencies_start=dependency_start,
                  created_utc=datetime.now(timezone.utc).isoformat(),
                  requested_candidate=str(source_directory),
                  control_mode=('explicit_C19_diagnostic' if source_control is not None
                                else 'disabled_new_seed_producers'))
    report['composition_ownership'] = dict(
        standalone_selected_screen=list(COMPOSITION_VARIANTS),
        standalone_ordinary=[variant for variant in COMPOSITION_VARIANTS
                             if variant != 'FSRDOutputCompTileAnchor'],
        paired_tile_light_anchor='Shared-UAV ownership is covered by the native driver suite')
    try:
        # Production may be working PRE; caller-supplied snapshots must already
        # authenticate themselves before being copied. Every dispatch below
        # consumes only this run's private, hash-audited snapshot.
        if source_directory != t.PRE.resolve():
            report['requested_candidate_identity'] = _frozen_identity(source_directory)
        _require_default_producers((source_directory / 'FSRDFloorSeed.hlsl').read_bytes())
        _require_default_macro((source_directory / 'FSRDFloorSeed.hlsl').read_bytes(), SPARSE_CONTROL_MACRO)
        source_files = _snapshot(source_directory, directory, 'candidate_snapshot')
        model_source = (directory / 'FSRDFloorModel.hlsli').read_text(encoding='utf-8')
        if '-101' not in model_source or '-102' not in model_source:
            raise ValueError('Candidate must declare both exact certificate class sentinels')
        candidate_id = _frozen_identity(directory)
        if source_control is None:
            _automatic_control(directory, control_directory)
        else:
            report['requested_control_identity'] = _frozen_identity(source_control)
            control_source_files = _snapshot(source_control, control_directory,
                                             'explicit_C19_diagnostic_control')
            _manifest(control_directory, purpose='explicit_C19_diagnostic_control', defines={},
                      source=str(source_control), source_files=control_source_files)
        control_id = _frozen_identity(control_directory)
        _automatic_control(directory, sparse_directory, macro=SPARSE_CONTROL_MACRO)
        sparse_id = _frozen_identity(sparse_directory)
        changed_sparse = [name for name in candidate_id['files']
                          if candidate_id['files'][name] != sparse_id['files'][name]]
        t.check('sparse-only control changes exactly three Seed assets and retains reference-control default0',
                sparse_id['purpose'] == 'disabled_sparse_uplift_only'
                and sparse_id['defines'] == {CONTROL_MACRO: 0, SPARSE_CONTROL_MACRO: 1}
                and sparse_id['files'].keys() == candidate_id['files'].keys()
                and set(changed_sparse) == {'FSRDFloorSeed.hlsl', 'FSRDFloorSeed_Shader.cso', 'FSRDFloorSeed_Shader.h'}
                and (sparse_directory / 'FSRDFloorSeed.hlsl').read_bytes() ==
                    ('#define ' + SPARSE_CONTROL_MACRO + ' 1\n').encode() + (directory / 'FSRDFloorSeed.hlsl').read_bytes(),
                changed_assets=changed_sparse)
        report.update(candidate=candidate_id, control=control_id)
        report['sparse_control'] = sparse_id
        if source_control is None:
            control_manifest = json.loads((control_directory.parent / 'shader_manifest.json').read_text(encoding='utf-8'))
            changed_seed_assets = {'FSRDFloorSeed.hlsl', 'FSRDFloorSeed_Shader.cso', 'FSRDFloorSeed_Shader.h'}
            audit = (control_id['purpose'] == 'disabled_new_seed_producers'
                     and control_id['defines'] == {CONTROL_MACRO: 1}
                     and control_manifest['compiled_only'] == ['FSRDFloorSeed']
                     and control_manifest['unchanged_consumers'] is True
                     and candidate_id['files'].keys() == control_id['files'].keys()
                     and all(candidate_id['files'][name] == control_id['files'][name]
                             for name in candidate_id['files'] if name not in changed_seed_assets))
            t.check('automatic control disables only the two Seed producers and reuses identical consumers', audit)
        t.check('CPU analytic lighting fixtures resolve their declared certificate classes',
                all(item['classification_passed'] for item in plan['resolution_physics']))
        with c.GPUWorker(output):
            for frame in list(clean_frames()) + list(resolved_frames()) + list(polynomial_frames()):
                active_seed, old_seed = _seed_pair(frame, directory, control_directory)
                _clean_contract(frame, active_seed, old_seed, directory, control_directory, records)
            for frame in noise_frames():
                active_seed, old_seed = _seed_pair(frame, directory, control_directory)
                _noise_contract(frame, active_seed, old_seed, directory, control_directory)
            for frame, centers, channels in cluster_frames():
                active_seed, old_seed = _seed_pair(frame, directory, control_directory)
                _cluster_contract(frame, centers, channels, active_seed, old_seed,
                                  directory, control_directory)
            for frame, boundary, left, right in boundary_frames():
                active_seed, old_seed = _seed_pair(frame, directory, control_directory)
                _boundary_contract(frame, boundary, left, right, active_seed, old_seed,
                                   directory, control_directory)
            _manual_carry(directory, control_directory)
            composition_dirs, composition_records = _composition_aliases(directory, output)
            report['composition_variants'] = composition_records
            _manual_conversion(directory, control_directory, stale_rr_guard, composition_dirs)
            report['sparse_metrics'] = _sparse_contract(directory, sparse_directory, output)
            report['model_transport_metrics'] = _model_transport_contract(directory, output)
    except (Exception, SystemExit):
        error = traceback.format_exc()
    finally:
        try:
            dependency_end = _dependency_identity()
            unchanged = (dependency_end == dependency_start and candidate_id is not None
                         and control_id is not None and source_files is not None
                         and _asset_identity(source_directory) == source_files
                         and _frozen_identity(directory) == candidate_id
                         and _frozen_identity(control_directory) == control_id
                         and sparse_id is not None and _frozen_identity(sparse_directory) == sparse_id
                         and (source_control is None or
                              _asset_identity(source_control) == control_source_files))
            t.check('entire harness and frozen shader snapshots stayed immutable', unchanged)
        except Exception:
            dependency_end = None
            t.check('entire harness and frozen shader snapshots stayed immutable', False)
            error = (error or '') + traceback.format_exc()
        report.update(checks=t.checks, dispatches=t.timings, clean_metrics=records,
                      candidate=candidate_id, control=control_id,
                      dependencies_end=dependency_end, error=error)
        diagnostics_zero = bool(t.timings) and all(
            item.get('debug_layer') == '1' and item.get('validation_errors') == '0'
            and item.get('validation_warnings') == '0' for item in t.timings)
        report['diagnostics_zero'] = diagnostics_zero
        report['contracts_passed'] = (error is None and diagnostics_zero
                                      and bool(t.checks) and all(item['passed'] for item in t.checks))
        (output / 'results.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        t.OUT, t.runner, t.checks, t.timings, t.counter = saved
    if not report['contracts_passed']:
        raise AssertionError('Coherent-lighting contracts failed; see ' + str(output / 'results.json'))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Backward-compatible alias for normal suite execution')
    parser.add_argument('--describe', action='store_true', help='CPU-only fixture and contract description')
    parser.add_argument('--shader-dir', type=Path)
    parser.add_argument('--control-dir', type=Path, help='Optional immutable C19 diagnostic; default builds the Seed-only disabled-producer control')
    parser.add_argument('--output', type=Path, help='Fresh directory; default FSRD_GPU_TEST_OUTPUT/floor_lighting_contract')
    parser.add_argument('--stale-rr-guard', choices=('required', 'pending'), default='required')
    args = parser.parse_args()
    if args.describe:
        print(json.dumps(description(), indent=2, allow_nan=False))
    else:
        run(args.shader_dir, args.output, args.control_dir, stale_rr_guard=args.stale_rr_guard)
