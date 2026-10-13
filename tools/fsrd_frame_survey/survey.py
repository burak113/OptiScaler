"""Read one-frame surveys and rank separate-lighting hypotheses, without RR replay.

No fitted signal is fed into production. A low residual is evidence for a pair,
not proof that the pair is an NRD input/output or that water will be stain-free.
"""
from resource_limits import prepare, memory_guard, peak_bytes
prepare()
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np


FORMATS = {
    1: ('<f4', 4), 2: ('<f4', 4), 5: ('<f4', 3), 6: ('<f4', 3),
    9: ('<f2', 4), 10: ('<f2', 4), 11: ('<u2', 4),
    15: ('<f4', 2), 16: ('<f4', 2), 33: ('<f2', 2), 34: ('<f2', 2), 35: ('<u2', 2),
    39: ('<f4', 1), 40: ('<f4', 1), 41: ('<f4', 1),
    53: ('<f2', 1), 54: ('<f2', 1), 56: ('<u2', 1), 60: ('u1', 1), 61: ('u1', 1),
    23: ('<u4', 1), 24: ('<u4', 1), 26: ('<u4', 1),
    27: ('u1', 4), 28: ('u1', 4), 29: ('u1', 4), 87: ('u1', 4),
    44: ('<u4', 1), 45: ('<u4', 1), 46: ('<u4', 1),
}
RGBA_FLOAT = {1, 2, 9, 10}


def decode_words(raw, fmt):
    """Little-endian DXGI words, including packed R11G11B10 and plane-0 depth."""
    fmt = int(fmt)
    data = np.asarray(raw)
    if fmt in (23, 24):
        v = data[..., 0].astype(np.uint32)
        return np.stack(((v & 1023)/1023, ((v >> 10) & 1023)/1023,
                         ((v >> 20) & 1023)/1023, (v >> 30)/3), -1).astype(np.float32)
    if fmt == 26:
        v = data[..., 0].astype(np.uint32)
        out = []
        for shift, bits in ((0, 6), (11, 6), (22, 5)):
            field = (v >> shift) & ((1 << (bits+5))-1)
            exp = field >> bits
            mantissa = field & ((1 << bits)-1)
            normal = (1+mantissa.astype(np.float32)/(1 << bits)) * np.exp2(exp.astype(np.float32)-15)
            value = np.where(exp == 0, mantissa.astype(np.float32)*2**(1-15-bits), normal)
            value = np.where(exp == 31, np.where(mantissa == 0, np.inf, np.nan), value)
            out.append(value)
        return np.stack(out, -1).astype(np.float32)
    if fmt in (44, 45, 46):
        return ((data.astype(np.uint32) & 0xffffff)/float(0xffffff)).astype(np.float32)
    out = data.astype(np.float32)
    if fmt in (11, 35, 56):
        out /= 65535
    if fmt in (27, 28, 29, 60, 61, 87):
        out /= 255
    if fmt == 87:
        out = out[..., [2, 1, 0, 3]]
    if fmt == 29:
        out[..., :3] = np.where(out[..., :3] <= .04045, out[..., :3]/12.92,
                                 ((out[..., :3]+.055)/1.055)**2.4)
    return out


def sample_image(raw, fmt, xy, render_extent, crop=(0, 0), source_extent=None):
    """Bilinear pixel-centre alignment; scaled candidate sampling is a hypothesis."""
    w, h = render_extent
    sh, sw = raw.shape[:2]
    native_w, native_h = source_extent or (sw, sh)
    px = (xy[:, 0]+.5)*native_w/w-.5-crop[0]
    py = (xy[:, 1]+.5)*native_h/h-.5-crop[1]
    px = np.clip(px, 0, sw-1); py = np.clip(py, 0, sh-1)
    x0 = np.floor(px).astype(int); y0 = np.floor(py).astype(int)
    x1 = np.minimum(x0+1, sw-1); y1 = np.minimum(y0+1, sh-1)
    ax = (px-x0)[:, None]; ay = (py-y0)[:, None]
    # Decode only sampled words. Keeping <=96 full decoded frames would be unsafe.
    a = decode_words(raw[y0, x0], fmt); b = decode_words(raw[y0, x1], fmt)
    c = decode_words(raw[y1, x0], fmt); d = decode_words(raw[y1, x1], fmt)
    return ((a*(1-ax)+b*ax)*(1-ay)+(c*(1-ax)+d*ax)*ay).astype(np.float32)


def radiance(samples, encoding):
    v = np.asarray(samples, dtype=np.float32)[..., :3]
    if encoding == 'RGB':
        return v
    if encoding == 'YCoCg':
        y, co, cg = np.moveaxis(v, -1, 0)
        return np.stack((y+co-cg, y+cg, y-co-cg), -1)
    raise ValueError(encoding)


def residual_stats(color, reconstructed):
    valid = np.isfinite(color).all(-1) & np.isfinite(reconstructed).all(-1)
    if not valid.any():
        return {'valid_samples': 0, 'mean_relative_l1': None}
    c = color[valid]; r = c-reconstructed[valid]
    mag = np.abs(c).sum(-1)
    floor = max(float(np.percentile(mag, 10))*.1, 1e-6)
    relative = np.abs(r).sum(-1)/np.maximum(mag, floor)
    return {
        'valid_samples': int(valid.sum()),
        'mean_relative_l1': float(np.abs(r).sum()/max(float(np.abs(c).sum()), 1e-6)),
        'median_pixel_relative_l1': float(np.median(relative)),
        'p90_pixel_relative_l1': float(np.percentile(relative, 90)),
        'p99_pixel_relative_l1': float(np.percentile(relative, 99)),
        'mean_signed_residual_rgb': r.mean(0).astype(float).tolist(),
        'negative_residual_channel_fraction': float((r < -floor/3).mean()),
    }


def search_pairs(color, qd, qs, candidates, top=12):
    """Exhaustive ORDERED pairs; no fitted gains and no same-resource pair.

    First half selects, second half is an independent holdout. Candidate keys
    carry resource IDs so different encodings/versions of the same resource do
    not masquerade as two independent lighting signals.
    """
    valid = np.isfinite(color).all(-1) & np.isfinite(qd).all(-1) & np.isfinite(qs).all(-1)
    color, qd, qs = color[valid, :3], qd[valid, :3], qs[valid, :3]
    entries = []
    for key, item in candidates.items():
        for encoding in ('RGB', 'YCoCg'):
            values = radiance(item['samples'][valid], encoding)
            if not np.isfinite(values).all() or values.shape[1] != 3:
                continue
            for modulation in ('albedo_demodulated', 'already_modulated'):
                entries.append((key, item['resource'], encoding, values, modulation))
    if len(color) < 32 or len(entries) < 2:
        return []
    cut = len(color)//2
    c = color[:cut]
    diffuse = np.stack([v[:cut]*(qd[:cut] if mod == 'albedo_demodulated' else 1) for _, _, _, v, mod in entries])
    specular = np.stack([v[:cut]*(qs[:cut] if mod == 'albedo_demodulated' else 1) for _, _, _, v, mod in entries])
    denominator = max(float(np.abs(c).sum()), 1e-6)
    rows = []
    for i, (key, resource, enc, values, modulation) in enumerate(entries):
        scores = np.abs(c[None]-diffuse[i]-specular).sum(axis=(1, 2))/denominator
        for j, entry in enumerate(entries):
            if resource == entry[1]:
                scores[j] = np.inf
        count = min(top, len(entries))
        for j in np.argsort(scores, kind='stable')[:count]:
            if np.isfinite(scores[j]):
                rows.append((float(scores[j]), i, int(j)))
    rows.sort()
    result = []
    for score, i, j in rows[:top]:
        x, y = entries[i], entries[j]
        reconstructed = x[3][cut:]*(qd[cut:] if x[4] == 'albedo_demodulated' else 1)+y[3][cut:]*(qs[cut:] if y[4] == 'albedo_demodulated' else 1)
        result.append({'diffuse': x[0], 'specular': y[0], 'diffuse_encoding_hypothesis': x[2],
                       'specular_encoding_hypothesis': y[2], 'selection_relative_l1': score,
                       'diffuse_modulation_hypothesis': x[4], 'specular_modulation_hypothesis': y[4],
                       'holdout': residual_stats(color[cut:], reconstructed),
                       'equation': 'Color = D*Qd + S*Qs + R, or already-modulated term; fixed unit coefficients'})
    return result


class Survey:
    def __init__(self, folder, verify=True):
        self.folder = Path(folder).resolve()
        self.manifest = json.loads((self.folder/'capture.json').read_text(encoding='utf-8'))
        if self.manifest.get('schema') != 'fsrd-frame-survey-v1':
            raise ValueError('Expected fsrd-frame-survey-v1, not GAME_TRACE/RR history data')
        self.extent = tuple(self.manifest['render_extent'])
        self.resources = {v['id']: v for v in self.manifest.get('resources', [])}
        self.images = {}
        published = self.manifest.get('manifest_published_frames', 0)
        frames = self.manifest.get('frames', [])[:published]
        for frame in frames:
            if not frame.get('cpu_snapshot_immutable') or not frame.get('submission_gate_protected'):
                raise ValueError('Unverified immutable GPU payload')
            for image in frame['images']:
                relative = Path(image['file'])
                path = (self.folder/relative).resolve()
                if relative.is_absolute() or self.folder not in path.parents:
                    raise ValueError('Image path leaves capture folder')
                if path.stat().st_size != image['bytes']:
                    raise ValueError(f'Payload byte mismatch: {relative}')
                if verify:
                    digest = hashlib.sha256()
                    with path.open('rb') as handle:
                        for chunk in iter(lambda: handle.read(1 << 20), b''):
                            digest.update(chunk)
                    if digest.hexdigest() != image['sha256']:
                        raise ValueError(f'Payload hash mismatch: {relative}')
                self.images[(frame['list_id'], image['name'])] = {**image, 'path': path}
        lists = {v['id']: v for v in self.manifest.get('command_lists', [])}
        self.passes = []
        self.order = {}
        for batch in self.manifest.get('batches', []):
            for position, lid in enumerate(batch['lists']):
                self.order[lid] = (batch['submission'], position)
                for row in lists.get(lid, {}).get('passes', []):
                    self.passes.append({**row, 'list_id': lid, 'submission': batch['submission'], 'queue': batch['queue']})
        self.snapshots = {}
        for row in self.manifest.get('snapshots', []):
            key = (row['list_id'], row['key'])
            if key in self.images:
                old = self.snapshots.get((row['resource'], row['subresource']))
                rank = (*self.order.get(row['list_id'], (-1, -1)), row['writer_local_pass'])
                if old is None or rank >= old['rank']:
                    self.snapshots[(row['resource'], row['subresource'])] = {**row, 'image_key': key, 'rank': rank}

    def samples(self, image_key, xy, view_format=None):
        image = self.images[image_key]
        fmt = int(view_format or image['dxgi_format'])
        if fmt not in FORMATS:
            raise ValueError(f'Unsupported DXGI format {fmt}')
        dtype, channels = FORMATS[fmt]
        w, h = image['extent']
        if w*h*np.dtype(dtype).itemsize*channels != image['bytes']:
            raise ValueError('Typed view and original word size disagree')
        raw = np.memmap(image['path'], mode='r', dtype=dtype, shape=(h, w, channels))
        if image['name'].startswith(('tag_', 'sl_')) and tuple(image['extent']) == self.extent:
            # A tag's logical subrect is already copied into the file. Padded
            # native allocation extents must not stretch that logical image.
            return sample_image(raw, fmt, xy, self.extent)
        return sample_image(raw, fmt, xy, self.extent, image.get('crop_origin', (0, 0)), image.get('source_extent'))

    def tag(self, name):
        aliases = {'Color': ('Color', 'ScalingInputColor'), 'DiffuseAlbedo': ('DiffuseAlbedo', 'Albedo'),
                   'Normals': ('Normals', 'NormalRoughness')}
        choices = []
        for row in self.manifest.get('tags', []):
            if row['name'] not in aliases.get(name, (name,)) or not row.get('snapshot_available'):
                continue
            key = (row['list_id'], row['snapshot_key'])
            if key in self.images:
                # NGX entry is later/more specific than a pre-evaluation SL tag call.
                choices.append((row.get('source') != 'current_Streamline_tag_call', key, row))
        if not choices:
            raise ValueError(f'Missing actual title tag snapshot: {name}')
        return sorted(choices, key=lambda v: v[0])[-1][1]

    def indirect_commands(self, row):
        meta = row.get('indirect', {})
        if not meta.get('arguments_available') or not meta.get('count_available'):
            return {'available': False, 'reason': 'argument_or_count_snapshot_unavailable'}
        key = (row['list_id'], meta['argument_key'])
        if key not in self.images:
            return {'available': False, 'reason': 'payload_not_published'}
        maximum = meta['maximum_command_count']
        if meta.get('count_buffer_present'):
            count_key = (row['list_id'], meta['count_key'])
            if count_key not in self.images:
                return {'available': False, 'reason': 'count_payload_not_published'}
            maximum = min(maximum, int(np.fromfile(self.images[count_key]['path'], dtype='<u4', count=1)[0]))
        layout = meta['signature']; stride = layout['byte_stride']
        raw = self.images[key]['path'].read_bytes()
        saved_count = min(maximum, len(raw)//stride)
        commands = []
        sizes = {0: 16, 1: 20, 2: 12, 3: 16, 4: 16, 6: 8, 7: 8, 8: 8, 9: 104, 10: 12}
        for command in range(saved_count):
            offset = command*stride
            decoded = []
            for arg in layout['arguments']:
                kind = arg['type']; size = arg.get('words', 0)*4 if kind == 5 else sizes.get(kind)
                if size is None or offset+size > (command+1)*stride:
                    return {'available': False, 'reason': 'unsupported_indirect_signature_layout', 'actual_command_count': maximum}
                if kind in (2, 10):
                    groups = np.frombuffer(raw, '<u4', count=3, offset=offset).astype(int).tolist()
                    decoded.append({'type': 'Dispatch' if kind == 2 else 'DispatchMesh', 'thread_group_counts': groups})
                elif kind in (0, 1):
                    decoded.append({'type': 'DrawInstanced' if kind == 0 else 'DrawIndexedInstanced',
                                    'argument_words': np.frombuffer(raw, '<u4', count=size//4, offset=offset).astype(int).tolist()})
                offset += size
            commands.append(decoded)
        return {'available': True, 'actual_command_count': maximum, 'decoded_command_count': saved_count,
                'capped': saved_count < maximum, 'commands': commands}


def identify_runs(survey):
    """Graph/event heuristic. Every returned NRD/method label remains a hypothesis."""
    resources = survey.resources
    groups = []; run = []
    for row in survey.passes:
        if row['kind'] in ('Dispatch', 'ExecuteIndirect'):
            run.append(row)
        else:
            if len(run) >= 4: groups.append(run)
            run = []
    if len(run) >= 4: groups.append(run)
    result = []
    for group in groups:
        ids = {v['resource'] for p in group for v in p.get('reads', [])}
        written = {v['resource'] for p in group for v in p.get('writes', [])}
        float_lobes = [i for i in ids if resources.get(i, {}).get('format') in RGBA_FLOAT and
                       (resources[i]['width'], resources[i]['height']) == survey.extent]
        viewz = [i for i in ids if resources.get(i, {}).get('format') in (39, 40, 41, 53, 54)]
        normals = [i for i in ids if resources.get(i, {}).get('format') in (23, 24, 27, 28, 9, 10)]
        mv = [i for i in ids if resources.get(i, {}).get('format') in (15, 16, 33, 34, 9, 10)]
        if len(float_lobes) < 2 or not viewz or not normals or not mv:
            continue
        events = ' '.join(' '.join(p.get('events', []))+' '+p.get('marker', '') for p in group).lower()
        method = 'unknown'
        if 'reblur' in events: method = 'REBLUR_event_label'
        elif 'relax' in events or 'atrous' in events or 'a-trous' in events: method = 'RELAX_event_structure'
        hashes = sorted({h for p in group for h in p.get('pso', {}).get('shader_hashes', {}).values()})
        result.append({'kind': 'NRD_compute_run_hypothesis', 'method_hypothesis': method,
                       'dispatches': len(group), 'start_pass': group[0]['local_pass'], 'end_pass': group[-1]['local_pass'],
                       'input_rgba_float_resources': float_lobes, 'potential_outputs': sorted(written),
                       'viewz_candidates': viewz, 'normal_candidates': normals, 'motion_candidates': mv,
                       'shader_hashes': hashes, 'proof_limit': 'bound views expose potential access; constants and method version not decoded'})
    return result


def points(extent, roi, count=4096, seed=11):
    w, h = extent
    x, y, rw, rh = roi or (0, 0, w, h)
    if min(x, y) < 0 or min(rw, rh) <= 0 or x+rw > w or y+rh > h:
        raise ValueError('ROI leaves render extent')
    rng = np.random.default_rng(seed)
    n = min(count, rw*rh)
    flat = rng.choice(rw*rh, n, replace=False)
    return np.stack((x+flat % rw, y+flat // rw), -1).astype(np.float32)


def analyze(folder, opaque_roi=None, water_roi=None, floor_roi=None):
    memory_guard(); started = time.perf_counter()
    survey = Survey(folder)
    output = {'source': str(survey.folder), 'complete': bool(survey.manifest.get('complete')),
              'survey_scope': 'one observed frame; no temporal stability or update stability claim',
              'coverage_gaps': survey.manifest.get('coverage_gaps', {}), 'passes': len(survey.passes),
              'verified_images': len(survey.images), 'nrd_run_hypotheses': identify_runs(survey),
              'evaluate_entries': survey.manifest.get('evaluate_entries', []), 'pairs': []}
    output['indirect_commands'] = [{'list_id': p['list_id'], 'local_pass': p['local_pass'],
                                    **survey.indirect_commands(p)} for p in survey.passes if p['kind'] == 'ExecuteIndirect']
    output['root_constant_prefixes'] = [{'list_id': p['list_id'], 'local_pass': p['local_pass'], 'buffers': p['root_constant_buffers']}
                                      for p in survey.passes if p.get('root_constant_buffers')]
    try:
        xy = points(survey.extent, opaque_roi)
        color_key = survey.tag('Color'); qd_key = survey.tag('DiffuseAlbedo'); qs_key = survey.tag('SpecularAlbedo')
        color = survey.samples(color_key, xy)[:, :3]
        qd = survey.samples(qd_key, xy)[:, :3]; qs = survey.samples(qs_key, xy)[:, :3]
        excluded = {row['resource'] for row in survey.manifest.get('tags', []) if row['name'] in
                    ('Color', 'ScalingInputColor', 'DiffuseAlbedo', 'Albedo', 'SpecularAlbedo', 'Normals', 'NormalRoughness', 'Depth', 'MotionVectors') and row.get('bound')}
        candidates = {}
        for (resource, sub), snapshot in survey.snapshots.items():
            image = survey.images[snapshot['image_key']]
            fmt = snapshot.get('view_format', image['dxgi_format'])
            if resource in excluded or fmt not in FORMATS or image['channels'] < 3 or snapshot.get('tagged'):
                continue
            key = f'r{resource}s{sub}'
            try:
                samples = survey.samples(snapshot['image_key'], xy, fmt)
            except ValueError:
                continue
            candidates[key] = {'resource': resource, 'samples': samples, 'image_key': snapshot['image_key'], 'format': fmt}
        output['candidate_count'] = len(candidates)
        output['candidate_inventory'] = []
        for key, item in candidates.items():
            samples = item['samples']; alpha = samples[:, 3] if samples.shape[1] == 4 else np.array([])
            finite = alpha[np.isfinite(alpha)]
            alpha_stats = {'finite_samples': int(len(finite)), 'semantic': 'unknown; range alone cannot prove normalized hit distance'}
            if len(finite):
                alpha_stats.update({'percentiles_0_10_50_90_100': np.percentile(finite, [0, 10, 50, 90, 100]).tolist(),
                                    'fraction_in_0_1': float(((finite >= 0) & (finite <= 1)).mean())})
            rid = item['resource']; image = survey.images[item['image_key']]
            def access_rows(kind):
                return [{'submission': p['submission'], 'list_id': p['list_id'], 'local_pass': p['local_pass'],
                         'events': p.get('events', []), 'pso': p.get('pso', {})} for p in survey.passes
                        if any(v['resource'] == rid for v in p.get(kind, []))]
            output['candidate_inventory'].append({'key': key, 'resource': survey.resources.get(rid), 'view_format': item['format'],
                'image_file': str(image['path']), 'sha256': image['sha256'], 'alpha_statistics': alpha_stats,
                'potential_writers': access_rows('writes'), 'potential_readers': access_rows('reads')})
        output['sample_region'] = {'roi': opaque_roi, 'semantic': 'user_opaque_ROI' if opaque_roi else 'whole_frame_no_opacity_claim', 'samples': len(xy)}
        output['pairs'] = search_pairs(color, qd, qs, candidates)
        if output['pairs']:
            best = output['pairs'][0]
            output['regional_consistency'] = {}
            for name, region in [('water', water_roi), ('floor_print', floor_roi)]:
                if not region: continue
                coords = points(survey.extent, region, seed=23)
                d = candidates[best['diffuse']]; s = candidates[best['specular']]
                ds = radiance(survey.samples(d['image_key'], coords, d['format']), best['diffuse_encoding_hypothesis'])
                ss = radiance(survey.samples(s['image_key'], coords, s['format']), best['specular_encoding_hypothesis'])
                c = survey.samples(color_key, coords)[:, :3]
                qd_roi = survey.samples(qd_key, coords)[:, :3]; qs_roi = survey.samples(qs_key, coords)[:, :3]
                dm = ds*(qd_roi if best['diffuse_modulation_hypothesis'] == 'albedo_demodulated' else 1)
                sm = ss*(qs_roi if best['specular_modulation_hypothesis'] == 'albedo_demodulated' else 1)
                output['regional_consistency'][name] = {'roi': region, 'residual': residual_stats(c, dm+sm),
                    'diffuse_radiance_mean_rgb': ds.mean(0).tolist(), 'specular_radiance_mean_rgb': ss.mean(0).tolist(),
                    'interpretation': 'single-frame observation; reflection-in-S versus later-R needs spatial inspection and both modes'}
        small = bool(output['pairs'] and output['pairs'][0]['holdout']['mean_relative_l1'] < .05)
        output['pair_result'] = 'candidate_pair_low_residual_hypothesis' if small else (
            'not_found_within_saved_candidates; coverage_or_encoding_gaps_prevent_global_negative' if output['coverage_gaps'] else
            'not_found_within_verified_saved_candidates_RGB_YCoCg_and_modulation_hypotheses')
    except ValueError as error:
        output['pair_result'] = 'inconclusive_missing_required_data'
        output['reason'] = str(error)
    output['recommendation'] = 'NO-GO_for_production_integration_until_signal_identity_encoding_and_two_mode_game_evidence_are_verified'
    output['seconds'] = time.perf_counter()-started
    output['peak_working_set_bytes'] = peak_bytes()
    if output['peak_working_set_bytes'] > 2.5*(1 << 30):
        raise MemoryError('Analysis exceeded 2.5 GiB process budget')
    return output


def roi_arg(text):
    value = tuple(map(int, text.split(',')))
    if len(value) != 4: raise argparse.ArgumentTypeError('Use x,y,width,height')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--opaque-roi', type=roi_arg)
    parser.add_argument('--water-roi', type=roi_arg)
    parser.add_argument('--floor-roi', type=roi_arg)
    args = parser.parse_args()
    result = analyze(args.capture, args.opaque_roi, args.water_roi, args.floor_roi)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({key: result.get(key) for key in ('pair_result', 'candidate_count', 'passes', 'verified_images', 'seconds', 'peak_working_set_bytes')}))


if __name__ == '__main__':
    main()
