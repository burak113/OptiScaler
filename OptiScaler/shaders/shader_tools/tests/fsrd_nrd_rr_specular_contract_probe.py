"""CPU-only geometry/roughness audit of the frozen V1 specular oracle.

Reports model boundaries; never changes V1, a production guide or a tolerance.
Analytic reflected-feature motion below is an observation, NOT the SDK primary
surface motion input. Opaque hit-distance words remain checked against V1.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_material_quality as model


def stats(values):
    values = np.asarray(values, np.float64).ravel()
    return dict(count=int(values.size), mean=float(np.mean(values)),
                median=float(np.median(values)), p95=float(np.quantile(values, .95)),
                max=float(np.max(values))) if values.size else dict(count=0)


def oct_normal(word):
    uv = np.array([word & 1023, (word >> 10) & 1023], np.float64) / 1023. * 2. - 1.
    normal = np.array([uv[0], uv[1], 1. - np.abs(uv).sum()])
    normal[:2] += np.sign(normal[:2]) * np.clip(-normal[2], 0., 1.)
    return normal / np.linalg.norm(normal)


def run(source, oracle_source, output):
    v1 = model.original(source)
    oracle = model.reference_oracle(oracle_source, v1['generator_sha256'])
    width, height = v1['width'], v1['height']
    y, x = np.mgrid[:height, :width]
    screen = np.stack((x + .5, y + .5), axis=-1) / (width, height)
    crop_x, crop_y, crop_width, crop_height = v1['comparison_crop']
    interior = (x >= crop_x) & (x < crop_x + crop_width) & (y >= crop_y) & (y < crop_y + crop_height)
    normal = None
    rows, all_normal_environment_error, all_motion_delta, all_segment_hit = [], [], [], []
    all_roughness, all_hit, all_thin_phase_error = [], [], []
    previous_pose = None
    for frame in v1['frames']:
        index, directory = frame['frame'] - 2, source / frame['directory']
        pose = oracle['pose'](index, width, height)
        uv = screen - pose['jitter'] / (width, height)
        current = oracle['trace'](uv, pose)
        point, object_mask = current['point'], current['object'].astype(bool)
        stored_world = model.load(directory, frame['payloads']['current_world'])
        model.require(np.array_equal(point.astype('<f4'), stored_world), 'exact independent current primary geometry')
        spec = model.load(directory, frame['payloads']['spec'])
        model.require(np.array_equal(spec[..., 3], current['spec_hit'].astype('<f2')), 'native hit A equals the declared environment intersection distance')
        packed = model.load(directory, frame['payloads']['normals'])
        model.require(np.unique(packed).size == 1, 'constant original packed normal/roughness; no probe replacement')
        word = int(packed[0, 0])
        decoded = oct_normal(word)
        if normal is None:
            normal = decoded
        model.require(np.array_equal(normal, decoded), 'all frames use identical packed normal')
        roughness = ((word >> 20) & 1023) / 1023.
        all_roughness.append(roughness)
        direction = point - pose['camera']
        direction /= np.linalg.norm(direction, axis=-1, keepdims=True)
        ideal_reflection = direction.copy()
        ideal_reflection[..., 2] *= -1.
        ideal_environment = point + ideal_reflection * current['spec_hit'][..., None]
        packed_reflection = direction - 2. * np.sum(direction * normal, axis=-1, keepdims=True) * normal
        packed_distance = (3. - point[..., 2]) / packed_reflection[..., 2]
        packed_environment = point + packed_reflection * packed_distance[..., None]
        environment_error = np.linalg.norm((packed_environment - ideal_environment)[..., :2], axis=-1)
        phase_error = np.abs((packed_environment - ideal_environment)[..., 0] * 18. +
                             (packed_environment - ideal_environment)[..., 1] * .6)
        all_normal_environment_error.append(environment_error[interior])
        all_thin_phase_error.append(phase_error[interior])
        all_hit.append(spec[..., 3][interior].astype(np.float64))
        # Test the explicitly visible foreground plane as a potential nearer
        # secondary hit. The sealed trace does not perform this intersection.
        t = (pose['center'][2] - point[..., 2]) / ideal_reflection[..., 2]
        crossing = point + ideal_reflection * t[..., None]
        nearer_rectangle = (~object_mask & (t > 0.) & (t < current['spec_hit']) &
            (np.abs(crossing[..., 0] - pose['center'][0]) <= .64) &
            (np.abs(crossing[..., 1] - pose['center'][1]) <= .95) & interior)
        all_segment_hit.append(int(np.count_nonzero(nearer_rectangle)))
        row = dict(frame=frame['frame'], roughness=roughness,
                   packed_normal_environment_xy_error=stats(environment_error[interior]),
                   foreground_secondary_segment_intersections=int(np.count_nonzero(nearer_rectangle)))
        if previous_pose is not None:
            # Fixed environment feature reflected in the previous mirror plane.
            # Translating foreground retains its previous plane Z/rectangle.
            z_previous = np.where(object_mask, previous_pose['center'][2], -8.)
            virtual = ideal_environment.copy()
            virtual[..., 2] = 2. * z_previous - 3.
            virtual_direction = virtual - previous_pose['camera']
            fraction = (z_previous - previous_pose['camera'][2]) / virtual_direction[..., 2]
            previous_mirror = previous_pose['camera'] + fraction[..., None] * virtual_direction
            feature_uv, _ = oracle['project'](previous_mirror, previous_pose)
            primary_previous = point + object_mask[..., None] * (previous_pose['center'] - pose['center'])
            primary_uv, _ = oracle['project'](primary_previous, previous_pose)
            previous_ray = oracle['trace'](feature_uv, previous_pose)
            visible = ((previous_ray['object'].astype(bool) == object_mask) &
                       (np.linalg.norm(previous_ray['point'] - previous_mirror, axis=-1) < 1e-7))
            inside = (feature_uv[..., 0] >= 0.) & (feature_uv[..., 0] < 1.) & (feature_uv[..., 1] >= 0.) & (feature_uv[..., 1] < 1.)
            valid = visible & inside & interior
            delta_pixels = np.linalg.norm((feature_uv - primary_uv) * (width, height), axis=-1)
            all_motion_delta.append(delta_pixels[valid])
            row['primary_vs_reflected_feature_previous_uv_pixels'] = stats(delta_pixels[valid])
            row['primary_vs_reflected_feature_background_pixels'] = stats(delta_pixels[valid & ~object_mask])
            row['primary_vs_reflected_feature_foreground_pixels'] = stats(delta_pixels[valid & object_mask])
        rows.append(row)
        previous_pose = pose
    model.require(len(set(all_roughness)) == 1, 'frozen normal B is constant throughout the history')
    result = dict(schema='fsrd-specular-oracle-contract-probe-v1', source_manifest_sha256=model.SOURCE_SHA,
        oracle_source_sha256=model.file_sha(oracle_source), packed_normal=normal.tolist(),
        packed_normal_angle_degrees=float(np.degrees(np.arccos(normal[2]))), roughness=all_roughness[0],
        perceptual_roughness_squared=all_roughness[0] ** 2,
        ideal_mirror_reference=True, rough_ggx_reference_integrated=False,
        packed_normal_environment_xy_error=stats(np.concatenate(all_normal_environment_error)),
        packed_normal_thin_phase_error=stats(np.concatenate(all_thin_phase_error)),
        spec_hit_distance=stats(np.concatenate(all_hit)),
        primary_vs_reflected_feature_previous_uv_pixels=stats(np.concatenate(all_motion_delta)),
        foreground_secondary_segment_intersections=sum(all_segment_hit),
        interior_samples=int(interior.sum()) * len(rows), frames=rows, checks=model.CHECKS,
        gpu_executed=False, compiler_executed=False, source_files_changed=False,
        interpretation=[
            'The source radiance/noise oracle is an ideal mirror point sample, not a rough-BRDF integral.',
            'The rounded oct normal is a legal quantized +Z approximation, but is not the exact +Z normal used by the analytic reflection ray.',
            'Secondary foreground intersections are a visibility-domain boundary; exact first-hit language needs an explicit environment-only secondary mask.',
            'SDK inputs require primary-surface motion; the analytic reflected-feature motion difference is diagnostic and must not replace it blindly.',
            'The SDK private virtual-hit implementation is opaque; no observation below proves that it uses this particular analytic construction.',
            'This audit cannot establish a production-normal, hit-distance or roughness mismatch in the game.'])
    model.write_json(output, result)
    print(json.dumps({key: value for key, value in result.items() if key != 'frames'}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    parser.add_argument('--oracle-source', type=Path, default=Path(__file__).resolve().parent / 'fsrd_nrd_motion_quality_oracle_v1_frozen.py')
    parser.add_argument('--output', type=Path, default=Path('E:/FSRD/sol_batch/15c-rr/specular-oracle-contract-probe.json'))
    args = parser.parse_args()
    run(args.source, args.oracle_source, args.output)


if __name__ == '__main__':
    main()
