"""D3D12 regression probes for the Floor affine lighting model.

Independent radiance truth and material guides exercise an affine fixed point,
HDR conditioning, impulse rejection and noise reduction together. These focused
contracts supplement the native AMD quality suites; they do not replace them.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as c


def run(directory=None, output=None):
    directory = directory or t.PRE
    t.OUT = output or t.OUT.parent / 'floor_model_contract'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    w, h = 65, 49
    y, x = np.indices((h, w))
    material = t.rgba(w, h, (0, 0, 0))
    for channel, phase in enumerate((.1, 1.2, 2.4)):
        material[..., channel] = (.43 + .16 * np.sin(.83*x + .21*y + phase)
                                   + .09 * np.cos(.71*y - .17*x - phase))
    normals = t.rgba(w, h, (0, 0, -1))
    depth = np.full((h, w), 10, np.float32)
    roi = (slice(7, -7), slice(7, -7), slice(0, 3))
    slope = np.array([.8, 1.1, .65], np.float32)
    intercept = np.array([.06, .04, .08], np.float32)
    clean = material.copy()
    clean[..., :3] = material[..., :3] * slope + intercept
    captured = {}

    def floor(raw, z=depth, n=normals, steps=(1, 2, 4, 8, 16)):
        cb = dict(InvProjMatrix=np.eye(4).ravel(), RenderSize=[w, h, 1/w, 1/h],
                  NearPlane=.1, FarPlane=1000, Flags=1, FloorEnabled=1)
        result, linear, guide, reference = t.dispatch('FSRDFloorSeed', cb,
            [raw, n, z, z, material], [10, 41, 10, 10], (w, h), directory)
        captured['reference'] = reference
        for step in steps:
            inputs = [result, linear, guide, material]
            if t.floor_has_detail_reference(directory):
                inputs.append(reference)
            result = t.dispatch('FSRDFloor', dict(DstTexSize=[w, h, 1/w, 1/h], StepSize=step),
                                inputs, [10], (w, h), directory)[0]
        captured['model'] = getattr(result, '_floor_model', None)
        return result

    for exposure in (.02, 1., 8000.):
        raw = clean * exposure
        result = floor(raw)
        error = (result[roi] - raw[roi]) / exposure
        rms = float(np.sqrt(np.mean(error**2)))
        signal = raw[roi] / exposure
        gain = float(np.sum((result[roi]/exposure - np.mean(result[roi]/exposure, axis=(0, 1))) *
                            (signal - np.mean(signal, axis=(0, 1)))) /
                     np.sum((signal - np.mean(signal, axis=(0, 1)))**2))
        t.check(f'affine material fixed point exposure {exposure}', rms < .003 and .98 < gain < 1.02,
                normalized_rmse=rms, contrast_gain=gain)
        t.check(f'affine model finite exposure {exposure}', np.isfinite(result).all())
        if captured['model'] is not None:
            model = captured['model'][7:-7, 7:-7].astype(np.float64)
            decoded = np.where(model[..., :3] > -99, np.exp2(model[..., :3]), 0)
            relative_error = np.abs(decoded / (slope * exposure) - 1)
            t.check(f'independent log slope precision exposure {exposure}',
                    np.isfinite(decoded).all() and float(np.max(relative_error)) < .02,
                    maximum_relative_coefficient_error=float(np.max(relative_error)))
        fast = floor(raw, steps=(1, 2, 16))
        fast_error = float(np.sqrt(np.mean(((fast[roi] - raw[roi]) / exposure)**2)))
        t.check(f'fast affine material fixed point exposure {exposure}', fast_error < .003,
                normalized_rmse=fast_error)

    original_material = material
    phase = np.sin(.83*x + .21*y)
    for label, coefficients, offset, low, span in (
        ('dark albedo high irradiance', [80000., 70000., 90000.], [0., 0., 0.], [.015]*3, [.009]*3),
        ('negative intercept cancellation', [2e6]*3, [-35000.]*3, [.03]*3, [.009]*3),
        ('heterogeneous RGB coefficients', [1e7, .125, .25], [0., 0., 0.], [.00005, .4, .5], [.00002, .12, .16]),
        ('zero albedo dim illumination', [.001]*3, [.0002]*3, [.15]*3, [.15]*3),
    ):
        material = t.rgba(w, h, (0, 0, 0))
        for channel in range(3):
            material[..., channel] = low[channel] + span[channel] * np.sin(.83*x+.21*y+channel*.9)
        if label == 'zero albedo dim illumination':
            material[16:19, 30:33, :3] = 0
            material[22:25, 30:33, :3] = [1e-6, 1e-5, 1e-4]
        raw = material.copy()
        raw[..., :3] = material[..., :3] * np.array(coefficients) + np.array(offset)
        for exposure in (.25, 1.):
            observation = raw * exposure
            result = floor(observation)
            for channel in range(3):
                target = observation[7:-7, 7:-7, channel].astype(np.float64)
                observed = result[7:-7, 7:-7, channel].astype(np.float64)
                signal_rms = np.sqrt(np.mean(target**2))
                error = observed - target
                nrmse = float(np.sqrt(np.mean(error**2)) / signal_rms)
                bias = float(abs(np.mean(error)) / signal_rms)
                centered = target - target.mean()
                gain = float(np.sum(centered*(observed-observed.mean())) / np.sum(centered**2))
                t.check(f'{label} exposure {exposure} channel {channel}',
                        nrmse < .02 and bias < .005 and .95 < gain < 1.05,
                        signal_nrmse=nrmse, channel_bias=bias, contrast_gain=gain)
            if label == 'zero albedo dim illumination':
                region = (slice(13, 28), slice(27, 36), slice(0, 3))
                relative_error = float(np.max(np.abs(result[region] - observation[region])) /
                                       np.max(observation[region]))
                t.check(f'exact-zero and near-zero material neighborhood exposure {exposure}',
                        relative_error < .02, maximum_relative_error=relative_error)
    material = original_material

    # Only three same-depth samples exist at this reveal. Their independently
    # known affine colour must be bounded immediately, including a nonzero offset.
    sparse_material = t.rgba(w, h, (.5, .5, .5))
    sparse_raw = t.rgba(w, h, (.018, .018, .018))
    sparse_depth = np.full((h, w), 3, np.float32)
    sparse = (h//2, slice(w//2-1, w//2+2), slice(0, 3))
    sparse_material[sparse] = [[.3, .4, .5], [.45, .5, .4], [.6, .35, .3]]
    sparse_truth = sparse_material[sparse] * slope + intercept
    sparse_raw[sparse] = sparse_truth
    sparse_depth[h//2, w//2-1:w//2+2] = 10
    material = sparse_material
    sparse_result = floor(sparse_raw, sparse_depth)
    sparse_error = sparse_result[sparse] - sparse_truth
    t.check('three independent reveal samples bound the affine model',
            float(np.max(np.abs(sparse_error))) < .003,
            maximum_absolute_error=float(np.max(np.abs(sparse_error))))
    material = original_material

    # A red transport slope grants no authority to blur a green/blue lighting
    # edge. Luminance is exactly equal on either side, so this needs an RGB gate.
    boundary_color = t.rgba(w, h, (0, .2, 6.15), .03)
    boundary_color[..., 0] = material[..., 0]
    boundary_color[:, w//2:, 1] = .8
    boundary_color[:, w//2:, 2] = 6.15 - .6 * .7152 / .0722
    boundary_albedo = material.copy()
    boundary_albedo[:, :w//2, 1:3] = [.2, .8]
    boundary_albedo[:, w//2:, 1:3] = [.8, .2]
    boundary_guide = t.rgba(w, h, (0, 0, 0))
    boundary_model = t.rgba(w, h, (0, -100, -100), 1)
    boundary_result = boundary_color
    for step in (1, 2, 4, 8, 16):
        model = getattr(boundary_result, '_floor_model', boundary_model)
        boundary_result = t.dispatch('FSRDFloor', dict(DstTexSize=[w,h,1/w,1/h], StepSize=step),
            [boundary_result, depth, boundary_guide, boundary_albedo,
             t.rgba(w,h,(0,0,0)), model], [10], (w,h), directory)[0]
    edge_region = (slice(7,-7), slice(w//2-3,w//2+3), slice(1,3))
    boundary_error = float(np.max(np.abs(boundary_result[edge_region] -
                                       boundary_color[edge_region])))
    # One FP16 spacing of the bright blue value is .00390625.
    t.check('single-channel model preserves an equal-luminance color boundary',
            boundary_error < .0041, maximum_absolute_error=boundary_error)
    inverse_material = boundary_albedo.copy()
    inverse_material[:, :w//2, 1:3] = [.8, .2]
    inverse_material[:, w//2:, 1:3] = [.2, .8]
    material = inverse_material
    full_boundary_result = floor(boundary_color)
    full_boundary_error = float(np.max(np.abs(full_boundary_result[edge_region] -
                                            boundary_color[edge_region])))
    t.check('seed cannot explain an unrelated color boundary with a red material model',
            full_boundary_error < .0041, maximum_absolute_error=full_boundary_error)

    # Neighbouring fits must not authorize replacement of an unrelated channel
    # or a centre whose raw lighting model was rejected. Verify final RGB energy,
    # including conversion and composition, rather than just model payload bits.
    authority_raw = t.rgba(w,h,(.4,.6,.5))
    authority_floor = t.rgba(w,h,(.3,.3,.3),.04)
    authority_albedo = t.rgba(w,h,(.5,.5,.5))
    authority_reference = t.rgba(w,h,(.4,.6,.5),.04)
    center_pixel = (h//2,w//2)
    for name, authority_model, center_payload in (
        ('rejected material channel',t.rgba(w,h,(0,0,0),1),[0,-100,-100,1]),
        ('rejected lighting plane',t.rgba(w,h,(-100,-100,-100),3),[-100,-100,-100,1.1]),
    ):
        authority_model[center_pixel] = center_payload
        authority_result = authority_floor
        hidden = authority_model
        for step in (1,2,4,8,16):
            authority_result = t.dispatch('FSRDFloor',dict(DstTexSize=[w,h,1/w,1/h],StepSize=step),
                [authority_result,depth,boundary_guide,authority_albedo,authority_reference,hidden],
                [10],(w,h),directory)[0]
            hidden = authority_result._floor_model
        packed = c.convert(authority_raw,authority_albedo,t.rgba(w,h,(.04,.04,.04)),
            floor=authority_result,reference=authority_reference,resources={17:hidden},directory=directory)
        reconstructed = c.compose(packed,detail=0,directory=directory)
        green_error = float(abs(reconstructed[center_pixel][1]-.6))
        t.check(name+' retains its independent source energy',green_error < .012,
                green_absolute_error=green_error,
                final_model=hidden[center_pixel].tolist())
    # Fits of different channels supply no common material transport. An
    # unrelated green slope cannot authorize crossing a red albedo boundary.
    disjoint_albedo = t.rgba(w,h,(.1,.5,.5))
    disjoint_albedo[center_pixel] = [.5,.5,.5,0]
    disjoint_floor = t.rgba(w,h,(.2,.4,.4),.1)
    disjoint_floor[center_pixel] = [.4,.4,.4,.1]
    disjoint_model = t.rgba(w,h,(-100,float(np.log2(.8)),-100),1)
    disjoint_model[center_pixel] = [float(np.log2(.8)),-100,-100,1]
    disjoint_reference = t.rgba(w,h,(.4,.4,.4),.04)
    hidden = disjoint_model
    for step in (1,2,4,8,16):
        disjoint_floor = t.dispatch('FSRDFloor',dict(DstTexSize=[w,h,1/w,1/h],StepSize=step),
            [disjoint_floor,depth,boundary_guide,disjoint_albedo,disjoint_reference,hidden],
            [10],(w,h),directory)[0]
        hidden = disjoint_floor._floor_model
    packed = c.convert(t.rgba(w,h,(.4,.4,.4)),disjoint_albedo,t.rgba(w,h,(.04,.04,.04)),
        floor=disjoint_floor,reference=disjoint_reference,resources={17:hidden},directory=directory)
    reconstructed = c.compose(packed,detail=0,directory=directory)
    red_error = float(abs(reconstructed[center_pixel][0]-.4))
    t.check('disjoint RGB fits retain the current material source',red_error < .002,
            red_absolute_error=red_error)

    # A trusted constant-material lighting model does not imply a globally
    # smooth light field. Keep active uncertainty to exercise the wide filter;
    # test the source split too, where a full model leaves no recoverable residual.
    for kind, left, right in (
        ('intensity', [.02, .02, .02], [1., 1., 1.]),
        ('equal luminance chroma', [.4, .2, .8], [.4, .25, .8 - .05*.7152/.0722]),
    ):
        for orientation, coordinate, extent in (('horizontal', x, w), ('vertical', y, h)):
            for edge in (2, extent//2, extent-2):
                source = t.rgba(w, h, left)
                source[coordinate >= edge, :3] = right
                reference = source.copy()
                reference[..., 3] = .02
                for mode, steps in (('full', (1, 2, 4, 8, 16)), ('fast', (1, 2, 16))):
                    current = source.copy()
                    current[..., 3] = .02
                    hidden = t.rgba(w, h, (-100, -100, -100), 3)
                    for step in steps:
                        current = t.dispatch('FSRDFloor', dict(DstTexSize=[w,h,1/w,1/h], StepSize=step),
                            [current, depth, boundary_guide, authority_albedo, reference, hidden],
                            [10], (w,h), directory)[0]
                        hidden = current._floor_model
                    packed = c.convert(source, authority_albedo, t.rgba(w,h,(.04,.04,.04)),
                        floor=current, reference=reference, resources={17:hidden}, directory=directory)
                    composed = c.compose(packed, detail=0, directory=directory)
                    error = float(np.max(np.abs(composed[..., :3]-source[..., :3])))
                    t.check(f'active plane {kind} {orientation} edge {edge} {mode}', error < .003,
                            maximum_absolute_error=error)
    for level in (.002, 32000.):
        source = t.rgba(w,h,(level, level, level))
        reference = source.copy()
        reference[...,3] = level*.04
        for mode, steps in (('full', (1,2,4,8,16)), ('fast', (1,2,16))):
            current = source.copy()
            current[...,3] = level*.04
            hidden = t.rgba(w,h,(-100,-100,-100),3)
            for step in steps:
                current = t.dispatch('FSRDFloor',dict(DstTexSize=[w,h,1/w,1/h],StepSize=step),
                    [current,depth,boundary_guide,authority_albedo,reference,hidden],
                    [10],(w,h),directory)[0]
                hidden = current._floor_model
            expected = source[...,:3].astype(np.float16).astype(np.float32)
            error = float(np.max(np.abs(current[...,:3]-expected)))
            t.check(f'active plane constant FP16 level {level} {mode}',
                    np.isfinite(current).all() and error == 0., maximum_absolute_error=error)
    material = t.rgba(w,h,(.5,.5,.5))
    normalized_x, normalized_y = x/(w-1), y/(h-1)
    for curvature in (0., .012):
        plane = t.rgba(w,h,(0,0,0))
        field = .4 + .08*normalized_x + .03*normalized_y + curvature*normalized_x*normalized_y
        plane[..., :3] = field[..., None]*np.array([.9,1.,1.1])
        for exposure in (.02,1.,8000.):
            plane_result = floor(plane*exposure)
            plane_error = float(np.sqrt(np.mean(((plane_result[roi]-plane[roi]*exposure)/exposure)**2)))
            t.check(f'clean flat lighting fixed point curvature {curvature} exposure {exposure}',
                    plane_error < .003, normalized_rmse=plane_error)
    material = original_material

    # A rejected ray on patterned material cannot grant transport permission to
    # spread its colour into adjacent clean texels, including channel-only rays.
    for channel in (-1, 0, 2):
        raw = clean.copy()
        if channel == -1:
            raw[h//2, w//2, :3] *= 30
        else:
            raw[h//2, w//2, channel] = 30
        result = floor(raw)
        patch = (slice(h//2-3, h//2+4), slice(w//2-3, w//2+4), slice(0, 3))
        error = result[patch] - clean[patch]
        t.check(f'material ray impulse has no halo channel {channel}', float(np.max(error)) < .02,
                maximum_added_radiance=float(np.max(error)))

    outputs, fast_outputs, inputs = [], [], []
    for frame in range(12):
        raw = clean.copy()
        raw[..., :3] += np.random.default_rng(741901+frame).normal(0, .025, (h, w, 3))
        inputs.append(raw[roi])
        outputs.append(floor(raw)[roi])
        fast_outputs.append(floor(raw, steps=(1,2,16))[roi])
    output_std = float(np.sqrt(np.mean(np.var(outputs, axis=0))))
    input_std = float(np.sqrt(np.mean(np.var(inputs, axis=0))))
    t.check('affine coefficients filter independent noise', output_std < input_std * .35,
            output_std=output_std, input_std=input_std)
    fast_std = float(np.sqrt(np.mean(np.var(fast_outputs,axis=0))))
    t.check('fast affine coefficients filter independent noise', fast_std < input_std*.35,
            output_std=fast_std,input_std=input_std)

    # Geometry changes while clean illumination remains constant. Newly exposed
    # texels get no temporal history and must retain their material immediately.
    images = []
    for boundary in (w//2-1, w//2, w//2+1, w//2+2):
        raw = clean.copy()
        z = depth.copy()
        hidden = x >= boundary
        z[hidden] = 3
        raw[hidden, :3] = .018
        images.append(floor(raw, z))
    for age, result in enumerate(images[1:]):
        column = w//2-1
        error = result[7:-7, column, :3] - clean[7:-7, column, :3]
        t.check(f'clean exposed material has immediate lighting age {age}', float(np.sqrt(np.mean(error**2))) < .003,
                rmse=float(np.sqrt(np.mean(error**2))))
    (t.OUT / 'results.json').write_text(json.dumps(dict(checks=t.checks, dispatches=t.timings,
                                                      purpose=__doc__), indent=2))
    if not all(row['passed'] for row in t.checks):
        raise AssertionError('Floor affine model contract failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shader-dir', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    run(args.shader_dir, args.output)
