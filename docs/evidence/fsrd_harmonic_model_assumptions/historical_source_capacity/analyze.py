"""Read-only spatial model-capacity diagnostic; no denoised/native output."""
from pathlib import Path
import hashlib
import json
import math
import time
import numpy as np

HERE = Path(__file__).resolve().parent
INPUT = Path('F:/Ultra Yedek 2/overwrite/bin/x64/RRTraceCaptures')
K_VALUES = (2, 8, 64)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def groups(h, w):
    yy, xx = np.indices((h, w))
    index = yy*w+xx
    partner = ((-yy) % h)*w+((-xx) % w)
    selected = (index <= partner) & (index != 0)
    return index[selected], partner[selected]

def spectral_view(rgb, window):
    h, w, _ = rgb.shape
    if window == 'rectangular':
        weight = np.ones((h, w))
    else:
        weight = np.outer(np.hanning(h), np.hanning(w))
    dc = np.sum(rgb*weight[..., None], axis=(0, 1))/np.sum(weight)
    centered = (rgb-dc)*weight[..., None]
    f = np.fft.fft2(centered, axes=(0, 1), norm='ortho')
    flat = f.reshape(-1, 3)
    first, partner = groups(h, w)
    energy = np.sum(abs(flat[first])**2, axis=1)
    energy += (first != partner)*np.sum(abs(flat[partner])**2, axis=1)
    total = float(np.sum(energy))
    direct = float(np.sum(centered**2))
    dc_energy = float(np.sum(abs(flat[0])**2))
    if not math.isclose(total+dc_energy, direct, rel_tol=2e-12, abs_tol=1e-18):
        raise AssertionError('Parseval/group decomposition failed')
    # Stable deterministic tie ordering; no optimizing window, ROI or K.
    order = np.lexsort((first, -energy))
    ordered = energy[order]
    cumulative = np.cumsum(ordered)
    def required(fraction):
        return None if total <= 1e-25 else int(np.searchsorted(cumulative, fraction*total)+1)
    top = []
    for rank in order[:2]:
        y, x = divmod(int(first[rank]), w)
        top.append({'cycles_y': float(np.fft.fftfreq(h)[y]*h),
                    'cycles_x': float(np.fft.fftfreq(w)[x]*w),
                    'energy_fraction': None if total <= 1e-25 else float(energy[rank]/total),
                    'self_conjugate': bool(first[rank] == partner[rank])})
    record = {
        'window': window, 'shape': [h, w, 3],
        'weighted_dc_RGB': dc.tolist(),
        'weighted_nonDC_RGB_RMS': float(np.sqrt(direct/(h*w*3))),
        'spatial_energy': direct, 'nonDC_group_energy': total,
        'DFT_DC_roundoff_energy': dc_energy,
        'pair_count': len(first),
        'topK_integer_pair_fraction': {str(k): None if total <= 1e-25 else float(np.sum(ordered[:k])/total) for k in K_VALUES},
        'pairs_for_50pct': required(.5), 'pairs_for_90pct': required(.9),
        'top2_integer_frequencies': top}
    return record, (f, first, partner, order, centered)

def selfchecks():
    rng = np.random.default_rng(583110)
    h, w = 30, 40
    y, x = np.indices((h, w))
    color1 = np.array([.3, .7, .5])
    color2 = np.array([.6, .2, .4])
    two = np.cos(2*np.pi*(3*x/w+2*y/h))[..., None]*color1
    two += np.sin(2*np.pi*(7*x/w-4*y/h))[..., None]*color2
    r, _ = spectral_view(two, 'rectangular')
    assert abs(r['topK_integer_pair_fraction']['2']-1) < 2e-14
    constant, _ = spectral_view(np.ones((h, w, 3)), 'rectangular')
    assert constant['topK_integer_pair_fraction']['2'] is None
    # Validate grouped top2 energy by an actual inverse-FFT projection.
    r, data = spectral_view(rng.normal(size=(h, w, 3)), 'rectangular')
    f, first, partner, order, centered = data
    chosen = np.zeros_like(f).reshape(-1, 3)
    flat = f.reshape(-1, 3)
    for k in order[:2]:
        chosen[first[k]] = flat[first[k]]
        chosen[partner[k]] = flat[partner[k]]
    reconstructed = np.fft.ifft2(chosen.reshape(h, w, 3), axes=(0, 1), norm='ortho')
    assert np.max(abs(reconstructed.imag)) < 2e-14
    ratio = np.sum(reconstructed.real**2)/np.sum(centered**2)
    assert abs(ratio-r['topK_integer_pair_fraction']['2']) < 2e-14
    offgrid = np.cos(2*np.pi*(3.37*x/w+2.19*y/h))[..., None]*color1
    offgrid_record, _ = spectral_view(offgrid, 'rectangular')
    return {'two_integer_wave_top2_fraction': 1.0,
            'direct_projection_ratio_error': float(abs(ratio-r['topK_integer_pair_fraction']['2'])),
            'offgrid_single_clean_wave_integer_top2_fraction': offgrid_record['topK_integer_pair_fraction']['2'],
            'offgrid_example_purpose': 'Shows integer basis concentration is not a continuous-atom capacity bound',
            'constant_zero_energy': True}

def main():
    start = time.perf_counter()
    freeze = json.loads((HERE/'pre_measurement_freeze.json').read_text())
    assert all(digest(HERE/k) == v for k, v in freeze['sources'].items())
    output = {'schema': 'historical-water-spatial-capacity-v1',
              'status': 'running', 'quality_accepted': False,
              'native_measured': False, 'source_temporal_quality_claim': False,
              'pre_measurement_freeze': freeze, 'selfchecks': selfchecks(),
              'rows': [], 'excluded_inventory': [], 'external_pins': []}
    directories = sorted(p for p in INPUT.iterdir() if p.is_dir())
    assert len(directories) == 20
    for folder in directories:
        metadata_path = folder/'capture.json'
        metadata = json.loads(metadata_path.read_text())
        output['external_pins'].append({'path': str(metadata_path), 'sha256': digest(metadata_path), 'bytes': metadata_path.stat().st_size})
        if metadata['schema_version'] == 1:
            output['excluded_inventory'].append({'capture_id': metadata['capture_id'], 'schema_version': 1,
                'origin_xy': metadata['origin_xy'], 'reason': 'No capture-recorded image hash and different ROI origin; excluded before measurements'})
            continue
        raw_meta = next(i for i in metadata['images'] if i['name'] in ('raw_rgba', 'raw_rgb'))
        raw_path = folder/raw_meta['file']
        raw_sha = digest(raw_path)
        assert raw_sha == raw_meta['sha256']
        h, w = int(raw_meta['height']), int(raw_meta['width'])
        assert metadata['complete'] and metadata['source'] == 'live_gpu'
        assert metadata['origin_xy'] == [752, 423]
        assert h >= 85 and w >= 85
        rgba = np.fromfile(raw_path, '<f4').reshape(h, w, 4)
        assert np.isfinite(rgba[..., :3]).all()
        roi = rgba[25:85, 5:85, :3].astype(np.float64)
        regions = [('full_crop', rgba[..., :3].astype(np.float64)),
                   ('historical_water_roi', roi)]
        regions.extend((f'roi_tile_{ty}_{tx}', roi[ty*30:(ty+1)*30, tx*40:(tx+1)*40]) for ty in range(2) for tx in range(2))
        records = []
        for name, rgb in regions:
            for window in ('rectangular', 'Hann'):
                record, _ = spectral_view(rgb, window)
                record['region'] = name
                records.append(record)
        output['external_pins'].append({'path': str(raw_path), 'sha256': digest(raw_path), 'bytes': raw_path.stat().st_size})
        output['rows'].append({'capture_id': metadata['capture_id'],
                               'schema_version': metadata['schema_version'],
                               'backend': metadata.get('backend', 'historical_split_schema3_or4'),
                               'scope': metadata.get('scope'),
                               'origin_xy': metadata.get('origin_xy'),
                               'source_raw_sha256_verified': True,
                               'records': records})
    assert len(output['rows']) == 14 and len(output['excluded_inventory']) == 6
    assert all(digest(HERE/k) == v for k, v in freeze['sources'].items())
    output['status'] = 'completed_descriptive_assumption_diagnostic'
    output['elapsed_seconds'] = time.perf_counter()-start
    (HERE/'results.json').write_text(json.dumps(output, indent=2, allow_nan=False)+'\n')
    compact = []
    for row in output['rows']:
        for r in row['records']:
            if r['region'] == 'historical_water_roi':
                compact.append({'capture_id': row['capture_id'], 'backend': row['backend'],
                                'window': r['window'], 'top2': r['topK_integer_pair_fraction']['2'],
                                'top8': r['topK_integer_pair_fraction']['8'],
                                'pairs90': r['pairs_for_90pct']})
    (HERE/'compact_results.json').write_text(json.dumps(compact, indent=2)+'\n')
    print(json.dumps({'status': output['status'], 'captures': len(output['rows']),
                      'views': sum(len(r['records']) for r in output['rows']),
                      'selfchecks': output['selfchecks'], 'elapsed_seconds': output['elapsed_seconds']}, indent=2))

if __name__ == '__main__':
    main()
