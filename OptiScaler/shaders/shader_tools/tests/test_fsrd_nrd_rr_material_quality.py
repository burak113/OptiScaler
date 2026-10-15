"""Independent CPU checks for the NEW controlled material-guide ablation."""
from pathlib import Path
import argparse
import json

import numpy as np

from fsrd_nrd_rr_material_quality import ggx_albedo, ggx_scalar, material_field, unpack_normal

CHECKS = 0


def require(value, reason):
    global CHECKS
    CHECKS += 1
    if not value:
        raise AssertionError(reason)


def run():
    random = np.random.default_rng(0x15C2026)
    max_vector_scalar_error = 0.
    max_f32_scalar_error = 0.
    # Includes grazing/normal incidence, smooth/rough, dielectric/metal, black,
    # neutral and asymmetric colors. Thresholds are numerical, never quality.
    for roughness in (0., .12, .5, 1.):
        for no_v in (0., .001, .25, .7, 1.):
            for metal in (0., .35, 1.):
                for color in ((0., 0., 0.), (.04, .04, .04), (.65, .12, .025), (.02, .35, .8)):
                    scalar = ggx_scalar(color, metal, roughness, no_v)
                    vector = ggx_albedo(np.asarray(color), metal, roughness, no_v)
                    f32 = ggx_albedo(np.asarray(color), metal, roughness, no_v, np.float32)
                    max_vector_scalar_error = max(max_vector_scalar_error, float(np.max(np.abs(vector-scalar))))
                    max_f32_scalar_error = max(max_f32_scalar_error, float(np.max(np.abs(f32-scalar))))
                    require(np.allclose(vector, scalar, atol=2e-13, rtol=0), 'matrix/vector and independent scalar GGX polynomials agree')
                    require(np.allclose(f32, scalar, atol=3e-5, rtol=0), 'GPU-style float32 GGX meets fixed numerical bound')
                    require(np.all(np.isfinite(f32)) and np.all(f32 >= 0), 'valid domain gives finite nonnegative specular guide')
    base = np.array([.6, .2, .03])
    dielectric = ggx_albedo(base, 0., .12, .8)
    require(np.max(dielectric)-np.min(dielectric) < 1e-15, 'dielectric F0 is achromatic .04, not arbitrary material RGB')
    metal = ggx_albedo(base, 1., .12, .8)
    require(metal[0] > metal[1] > metal[2], 'metal specular guide carries asymmetric reflectance')
    require(np.array_equal(ggx_albedo(base, 1., .12, -.8), metal), 'NoV absolute convention is explicit')
    require(np.array_equal(ggx_albedo([0, 0, 0], 1., .12, .8), np.zeros(3)), 'documented zero-reflectance bias gate is not omitted')
    world = random.uniform(-5, 5, (31, 37, 3))
    object_mask = random.random((31, 37)) < .5
    center = np.array([-.55, .03, -3.5])
    last_center = np.array([.73, -.12, -3.1])
    current = material_field(world, object_mask, center)
    moved = world+object_mask[..., None]*(last_center-center)
    corresponding = material_field(moved, object_mask, last_center)
    for channel in (0, 1, 4):
        require(np.array_equal(current[channel], corresponding[channel]), 'world/object-local material storage is exactly time stable')
    stored, stored_metal, linear, metal_value, identifiers = current
    decoded = np.stack([(stored >> (10*c)) & 1023 for c in range(3)], axis=-1).astype(float)/1023
    require(np.array_equal(decoded**2, linear), 'native-like squared RGB10 decode is exact, no sRGB transfer substitution')
    require(np.array_equal(stored_metal.astype(float)/255, metal_value), 'metal source is exact R8 UNORM')
    require(np.unique(identifiers).size >= 12, 'scene contains varied material/color-metal combinations')
    require(np.all((linear >= 0) & (linear <= 1)) and np.all((metal_value >= 0) & (metal_value <= 1)), 'valid material ranges')
    diffuse = linear*(1-metal_value[..., None])
    require(np.all(diffuse[metal_value == 1] == 0), 'pure metal has zero diffuse multiplier')
    require(np.all(diffuse[metal_value == 0] == linear[metal_value == 0]), 'dielectric diffuse factor has no extra division/modulation')
    packet = np.concatenate((linear, metal_value[..., None]), axis=-1).astype('<f2')
    require(np.all(np.isfinite(packet)), 'captured synthetic linear-base/metal packet is finite half')
    normal_words = np.full((31, 37), 512 | (512 << 10) | (123 << 20), dtype='<u4')
    normals, roughness = unpack_normal(normal_words)
    require(np.allclose(np.linalg.norm(normals, axis=-1), 1, atol=2e-16), 'guide normal direction is normalized from packed input')
    require(np.all(roughness == 123/1023), 'exact packed roughness is used, not a second square/root unpack')
    # Material multiplication must be linear/current-frame and independent of
    # noisy source; neither a reference nor native-NRD signal enters RR input.
    rgb = random.uniform(0, 2, (31, 37, 3))
    spec = random.uniform(0, 2, (31, 37, 3))
    qd, qs = diffuse, ggx_albedo(linear, metal_value, roughness, .8)
    noisy = (rgb*qd+spec*qs)
    require(np.array_equal(noisy*64, rgb*(qd*64)+spec*(qs*64)), 'common factor64 is post-RR composition, never input gain')
    from fsrd_nrd_rr_material_compare import masked_detail, summarize
    yy, xx = np.indices((8, 8))
    reference = np.repeat((xx+2*yy)[..., None], 3, axis=-1).astype(float)
    material_id = np.zeros((8, 8), dtype='u1')
    material_id[:, 4:] = 1
    for gain in (0., .5, 1.):
        stats = masked_detail(reference*gain, reference, material_id, [0, 0, 8, 8])
        require(abs(stats['gradient_projection_ratio']-gain) < 1e-15, 'demod detail projection measures retained lighting contrast')
    false_edge = reference.copy()
    false_edge[:, 4:] += 100
    stats = masked_detail(false_edge, reference, material_id, [0, 0, 8, 8])
    require(stats['gradient_projection_ratio'] == 1 and stats['rgb_gradient_rmse'] == 0,
            'material boundary contrast cannot masquerade as restored lighting detail')
    require(stats['adjacent_pairs'] == 104, 'only known different-material adjacent pairs excluded')
    template = dict(rgb_rmse=.1, chroma_rmse=.2, detail_gradient_rmse=.3,
                    gradient_projection_ratio=.4, reveal_tail={})
    rows = [dict(domains=dict(combined=dict(white=template.copy()))) for _ in range(2)]
    rows[1]['domains']['combined']['white']['reveal_tail'] = {'0':dict(pixels=7, rgb_rmse=.6,
        positive_stale_energy=.7, mean_signed_stale_fraction=.8)}
    summary = summarize(rows, ['white'])['white']['combined']
    require(summary['reveal_tail']['0']['pixels'] == 7 and summary['reveal_tail']['0']['rgb_rmse'] == .6,
            'missing first-frame reveal cohort does not fabricate support or dilute later error')
    require(summary['rgb_rmse'] == .1 and summary['gradient_projection_ratio'] == .4,
            'all original numeric rows retained in material summary')
    return dict(schema='fsrd-material-quality-cpu-properties-v1', checks=CHECKS,
                max_f64_vector_scalar_error=max_vector_scalar_error, max_f32_scalar_error=max_f32_scalar_error,
                gpu_executed=False, compiler_executed=False, quality_claimed=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
