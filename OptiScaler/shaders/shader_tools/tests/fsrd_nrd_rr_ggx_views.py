"""Immutable signal-domain adapters for the separate positive-GGX V5 oracle.

Physical path references are never overwritten. Optional demod views divide
only that explicitly PHYSICAL synthetic RGB by the exact positive quantized
guide, once. They do not transform already-demodulated native title signals.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_ggx_oracle as oracle
import fsrd_nrd_rr_material_quality as sealed
import fsrd_nrd_rr_mirror_oracle as scene


DEMOD_SCHEMA = oracle.SCHEMA + '-guide-defined-demod'
CHECKS = 0


def need(condition, message):
    global CHECKS
    CHECKS += 1
    if not bool(condition):
        raise AssertionError(message)


def load_frame(root, manifest, frame, names=None):
    physical = Path(manifest['physical_case']) if manifest['schema'] == DEMOD_SCHEMA else root
    fields = frame['payloads'] if names is None else {name: frame['payloads'][name] for name in names}
    derived = set(frame.get('derived_names', []))
    return {name: sealed.load((root if name in derived else physical) / 'dataset' / frame['directory'], info)
            for name, info in fields.items()}


def quantized_guide(roughness, no_v):
    dimensions = np.shape(no_v)
    full = sealed.ggx_albedo(np.ones(dimensions + (3,)), np.ones(dimensions), roughness, no_v)
    return np.rint(np.clip(full, 0., 1.) * 255.).astype('u1').astype(np.float64) / 255.


def divide_physical(noisy_rgba, qs):
    """Returns a new half texture and the exact inverse-quantization evidence."""
    need(np.isfinite(qs).all() and np.all(qs > 0.), 'chosen synthetic Qs is finite and strictly positive; no epsilon substitute')
    result = np.asarray(noisy_rgba, '<f2').copy()
    result[..., :3] = (result[..., :3].astype(np.float64) / qs).astype('<f2')
    need(np.array_equal(np.ascontiguousarray(result[..., 3]).view('<u2'),
                        np.ascontiguousarray(noisy_rgba[..., 3]).view('<u2')), 'hit-alpha words remain exact through one synthetic RGB divide')
    value = result[..., :3]
    decoded = value.astype(np.float64)
    up = np.nextafter(value, np.float16(np.inf)).astype(np.float64)
    down = np.nextafter(value, np.float16(-np.inf)).astype(np.float64)
    bound = .5 * np.maximum(up - decoded, decoded - down) * qs
    error = np.abs(decoded * qs - noisy_rgba[..., :3].astype(np.float64))
    need(np.isfinite(result[..., :3]).all() and np.all(error <= bound + 1e-15), 'physical roundtrip stays inside independent nearest-half bound')
    return result, dict(max_abs_roundtrip_error=float(np.max(error)), max_half_bound=float(np.max(bound)),
                       roundtrip_rgb_rmse=float(np.sqrt(np.mean(error * error))))


def derive(physical_case, destination):
    manifest = json.loads((physical_case / 'ggx-sequence.json').read_bytes())
    need(manifest['schema'] == oracle.SCHEMA and not manifest['zero_roughness_used'], 'source is explicit physical positive-GGX radiance, never native/demod data')
    need(not destination.exists() and destination.resolve().is_relative_to(scene.BASE.resolve()), 'fresh task-local derived view; preserve expensive physical sources')
    destination.mkdir(parents=True)
    # The native harness consumes only its seven named inputs. Sharing this
    # directory with immutable references avoids another full specular copy.
    view = destination / 'dataset'
    sealed.immutable(view / 'native-replay.txt', (physical_case / 'native-replay.txt').read_bytes())
    camera = oracle.camera_api()
    frames, quantization = [], []
    previous_qs = previous_age = None
    for index, frame in enumerate(manifest['frames']):
        data = load_frame(physical_case, manifest, frame)
        qs = data['spec_albedo'][..., :3].astype(np.float64) / 255.
        geometry = oracle.frame_geometry(index, camera)
        need(np.array_equal(data['motion'], geometry['motion']), 'recomputed cohort addressing uses exact original quantized primary motion')
        need(np.array_equal(qs, quantized_guide(manifest['roughness'], geometry['current']['no_v'])), 'denominator equals the exact actual RR guide, not F0 or guessed exposure')
        ghost_qs = np.ones((128, 128, 3), np.float64)
        age = data['reveal_age']
        new = age == 0
        carried = (age > 0) & (age <= 32)
        if index:
            sy, sx = geometry['sy'], geometry['sx']
            need(np.all(previous_age[sy[carried], sx[carried]].astype(int) + 1 == age[carried]), 'carried ghost denominator follows same historical cohort as physical ghost radiance')
            ghost_qs[carried] = previous_qs[sy[carried], sx[carried]]
        else:
            need(not new.any() and not carried.any(), 'first sample has no historical ghost')
        old_no_v = geometry['previous_visible']['no_v']
        ghost_qs[new] = quantized_guide(manifest['roughness'], old_no_v[new])
        spec, error = divide_physical(data['spec'], qs)
        quantization.append(error)
        arrays = dict(spec=spec, qs_current=qs.astype('<f4'), qs_historical_ghost=ghost_qs.astype('<f4'))
        for suffix in ('a', 'b'):
            arrays['reference_spec_' + suffix] = (data['reference_spec_' + suffix].astype(np.float64) / qs).astype('<f4')
            arrays['ghost_spec_' + suffix] = (data['ghost_spec_' + suffix].astype(np.float64) / ghost_qs).astype('<f4')
        arrays['reference_spec'] = ((arrays['reference_spec_a'].astype(np.float64) + arrays['reference_spec_b']) * .5).astype('<f4')
        arrays['ghost_spec'] = ((arrays['ghost_spec_a'].astype(np.float64) + arrays['ghost_spec_b']) * .5).astype('<f4')
        folder = destination / 'dataset' / frame['directory']
        folder.mkdir(parents=True)
        payloads = dict(frame['payloads'])
        payloads.update({name: sealed.put(folder, name + '.bin', value) for name, value in arrays.items()})
        native = view / frame['directory']
        native.mkdir(exist_ok=True)
        for name in ('spec', 'diff', 'depth', 'motion', 'normals', 'spec_albedo', 'diff_albedo'):
            source = folder if name == 'spec' else physical_case / 'dataset' / frame['directory']
            sealed.immutable(native / (name + '.bin'), (source / payloads[name]['file']).read_bytes())
        frames.append(dict(frame=frame['frame'], directory=frame['directory'], payloads=payloads, derived_names=list(arrays)))
        previous_qs, previous_age = ghost_qs, age
    result = dict(manifest, schema=DEMOD_SCHEMA, physical_case=str(physical_case),
        physical_manifest_sha256=sealed.file_sha(physical_case / 'ggx-sequence.json'),
        views={f'ggx-r{manifest["code"]}-demod': str(view)}, frames=frames,
        signal_definition='Ldemod=Lphysical/QsChosen; source is newly integrated physical synthetic radiance; no native signal transformation',
        qs_definition='exact positive linear RGB8_UNORM guide supplied to RR, pinned AMD F0=1ApproximateBRDF, synthetic choice rather than native title LUT',
        reference_definition='independent physical FP32 replicas /QsChosen, FP32 storage; both retained',
        ghost_definition='old physical ghost /QsChosen at its historical visibility source, cohort denominator carried; never oldphysical/currentQs',
        remodulation_metric='actualRRoutput*CURRENT QsChosen compared to original physical reference replicas; Consumer64 remains a common postscale',
        rgb_input_quantization=quantization, derived_source_sha256=sealed.file_sha(Path(__file__)),
        native_recon_parity_claimed=False, double_demodulation=False, checks=CHECKS)
    sealed.write_json(destination / 'ggx-sequence.json', result)
    print(json.dumps(dict(destination=str(destination), checks=CHECKS,
        manifest_sha256=sealed.file_sha(destination / 'ggx-sequence.json'),
        max_abs_roundtrip_error=max(row['max_abs_roundtrip_error'] for row in quantization),
        gpu_executed=False, compiler_executed=False), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--physical-case', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    derive(args.physical_case, args.output)


if __name__ == '__main__':
    main()
