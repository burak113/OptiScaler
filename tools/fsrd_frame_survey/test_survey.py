"""Synthetic signals only: validates pair ranking, word decoding and capture trust."""
from resource_limits import prepare, peak_bytes
prepare()
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from survey import Survey, analyze, decode_words, identify_runs, radiance, search_pairs

checks = 0


def need(value, description):
    global checks
    if not value:
        raise AssertionError(description)
    checks += 1


def synthetic(folder, encoding='RGB'):
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(11013)
    w, h = 64, 48
    d = rng.uniform(.2, 3, (h, w, 3)).astype(np.float32)
    s = rng.uniform(.05, 1.7, (h, w, 3)).astype(np.float32)
    qd = rng.uniform(.15, .85, (h, w, 3)).astype(np.float32)
    qs = rng.uniform(.03, .4, (h, w, 3)).astype(np.float32)
    residual = np.full((h, w, 3), .002, np.float32)
    residual[8:24, 8:24] += .8  # A synthetic later-composited water region.
    color = d*qd+s*qs+residual
    def packed(v, alpha):
        if encoding == 'YCoCg':
            r, g, b = np.moveaxis(v, -1, 0)
            v = np.stack(((r+2*g+b)/4, (r-b)/2, (-r+2*g-b)/4), -1)
        return np.concatenate((v, np.full((h, w, 1), alpha, np.float32)), -1)
    arrays = {'r10s0': packed(d, .2), 'r11s0': packed(s, .6)}
    for i in range(12, 29):
        arrays[f'r{i}s0'] = np.concatenate((rng.uniform(0, 5, (h, w, 3)), np.ones((h, w, 1))), -1).astype(np.float32)
    arrays['r29s0'] = np.concatenate((color, np.ones((h, w, 1))), -1)  # The combined-color distractor must be excluded.
    for name, v in [('Color', color), ('DiffuseAlbedo', qd), ('SpecularAlbedo', qs)]:
        arrays[f'tag_{name}_r{1 if name == "Color" else 2 if name == "DiffuseAlbedo" else 3}'] = np.concatenate((v, np.ones((h, w, 1))), -1)
    images = []; snapshots = []; tags = []; resources = []
    for key, v in arrays.items():
        v = v.astype('<f4')
        path = folder/f'{key}.bin'; path.write_bytes(v.tobytes())
        tagged = key.startswith('tag_')
        resource = int(key.rsplit('_r', 1)[1]) if tagged else int(key[1:key.index('s')])
        images.append({'name': key, 'file': path.name, 'dxgi_format': 2, 'channels': 4, 'bytes_per_pixel': 16,
                       'extent': [w, h], 'source_extent': [w, h], 'crop_origin': [0, 0],
                       'bytes': path.stat().st_size, 'sha256': hashlib.sha256(v.tobytes()).hexdigest()})
        snapshots.append({'key': key, 'list_id': 41, 'resource': resource, 'subresource': 0,
                          'writer_local_pass': 3, 'tagged': tagged, 'view_format': 2})
        resources.append({'id': resource, 'width': w, 'height': h, 'format': 2})
        if tagged:
            tags.append({'name': key.split('_')[1], 'list_id': 41, 'snapshot_key': key,
                         'snapshot_available': True, 'bound': True, 'resource': resource})
    # Mark the deliberately planted combined-color alias as the Color tag too.
    tags.append({'name': 'Color', 'bound': True, 'resource': 29, 'snapshot_available': False})
    manifest = {'schema': 'fsrd-frame-survey-v1', 'render_extent': [w, h], 'complete': True,
                'manifest_published_frames': 1, 'frames': [{'ordinal': 0, 'list_id': 41,
                'cpu_snapshot_immutable': True, 'submission_gate_protected': True, 'images': images}],
                'resources': resources, 'snapshots': snapshots, 'tags': tags,
                'batches': [{'submission': 0, 'queue': 7, 'lists': [41]}],
                'command_lists': [{'id': 41, 'passes': []}], 'coverage_gaps': {}}
    (folder/'capture.json').write_text(json.dumps(manifest), encoding='utf-8')
    return color, qd, qs, d, s, residual


def run(output):
    started = time.perf_counter()
    cases = {}
    for encoding in ('RGB', 'YCoCg'):
        folder = output/encoding
        color, qd, qs, d, s, r = synthetic(folder, encoding)
        result = analyze(folder, (32, 0, 32, 48), (8, 8, 16, 16), (32, 8, 16, 16))
        best = result['pairs'][0]
        need(best['diffuse'] == 'r10s0' and best['specular'] == 'r11s0', f'{encoding}: planted ordered pair wins among 17 distractors')
        need(best['diffuse_encoding_hypothesis'] == encoding and best['specular_encoding_hypothesis'] == encoding, 'encoding recovered')
        need(best['holdout']['mean_relative_l1'] < .004, 'opaque independent holdout has small known residual')
        water = result['regional_consistency']['water']['residual']['mean_relative_l1']
        need(water > .25, 'later-composited synthetic water is large in R')
        need(result['candidate_count'] == 19, 'combined color and tagged guides excluded, 2 signals plus 17 distractors retained')
        need(result['recommendation'].startswith('NO-GO'), 'low residual alone never approves integration')
        need(result['peak_working_set_bytes'] < 2.5*(1 << 30), 'memory cap')
        cases[encoding] = {'best': best, 'candidate_count': result['candidate_count'], 'water_relative_l1': water}
        survey = Survey(folder)
        need(len(survey.images) == 23, 'all published image hashes verified')
    # Half buffers and nonfinite/distractor rejection exercise the numerical core.
    rng = np.random.default_rng(19)
    color, qd, qs, d, s, r = synthetic(output/'negative')
    shape = color.reshape(-1, 3).shape
    distractors = {str(i): {'resource': i, 'samples': rng.uniform(2, 8, shape).astype(np.float32)} for i in range(7)}
    pairs = search_pairs(color.reshape(-1, 3), qd.reshape(-1, 3), qs.reshape(-1, 3), distractors)
    need(pairs[0]['holdout']['mean_relative_l1'] > .2, 'negative survey has no low-residual pair')
    need(all(p['diffuse'] != p['specular'] for p in pairs), 'same-resource pairs excluded')
    modulated = {'d': {'resource': 10, 'samples': (d*qd).reshape(-1, 3)}, 's': {'resource': 11, 'samples': (s*qs).reshape(-1, 3)}}
    modulated_pair = search_pairs((d*qd+s*qs).reshape(-1, 3), qd.reshape(-1, 3), qs.reshape(-1, 3), modulated)[0]
    need(modulated_pair['diffuse_modulation_hypothesis'] == modulated_pair['specular_modulation_hypothesis'] == 'already_modulated', 'already modulated signals do not get multiplied twice')
    need(modulated_pair['holdout']['mean_relative_l1'] < 1e-6, 'already modulated independent holdout is exact')
    distractors['nan'] = {'resource': 100, 'samples': np.full(shape, np.nan, np.float32)}
    need(all(p['diffuse'] != 'nan' and p['specular'] != 'nan' for p in search_pairs(color.reshape(-1, 3), qd.reshape(-1, 3), qs.reshape(-1, 3), distractors)), 'nonfinite candidates rejected')
    packed = np.array([[1023 | (512 << 10) | (256 << 20) | (3 << 30)]], dtype='<u4')
    need(np.allclose(decode_words(packed, 24), [[1, 512/1023, 256/1023, 1]]), '10-10-10-2 word decoding')
    value = (15 << 6) | ((15 << 6) << 11) | ((15 << 5) << 22)
    need(np.allclose(decode_words(np.array([[value]], dtype='<u4'), 26), [[1, 1, 1]]), 'packed R11G11B10 unit floats')
    need(np.allclose(decode_words(np.array([[0]], dtype='<u4'), 26), [[0, 0, 0]]), 'packed float subnormal zero')
    need(np.allclose(decode_words(np.array([[0x00ffffff]], dtype='<u4'), 46), [[1]]), 'depth plane-0 decoding')
    need(np.allclose(decode_words(np.array([[0, 128, 255, 255]], dtype='u1'), 87), [[1, 128/255, 0, 1]]), 'BGRA channel order')
    folder = output/'RGB'; manifest_path = folder/'capture.json'; manifest = json.loads(manifest_path.read_text())
    original = manifest_path.read_bytes()
    manifest['manifest_published_frames'] = 0; manifest_path.write_text(json.dumps(manifest))
    need(not Survey(folder).images, 'unpublished payloads never analyzed')
    manifest_path.write_bytes(original)
    manifest = json.loads(original)
    manifest['frames'][0]['images'][0]['file'] = '../outside.bin'; manifest_path.write_text(json.dumps(manifest))
    try: Survey(folder)
    except ValueError: checks_before = True
    else: checks_before = False
    need(checks_before, 'manifest path traversal refused')
    manifest_path.write_bytes(original)
    image_path = folder/'r10s0.bin'; data = image_path.read_bytes(); image_path.write_bytes(bytes([data[0] ^ 255])+data[1:])
    try: Survey(folder)
    except ValueError: rejected = True
    else: rejected = False
    need(rejected, 'changed GPU words fail SHA256 verification'); image_path.write_bytes(data)
    # A small artificial compute graph validates the run hypothesis only.
    survey = Survey(folder)
    survey.resources.update({100: {'format': 41}, 101: {'format': 24}, 102: {'format': 34}})
    survey.passes = [{'kind': 'Dispatch', 'local_pass': i, 'events': ['NRD', 'REBLUR'],
                     'reads': [{'resource': r} for r in (10, 11, 100, 101, 102)],
                     'writes': [{'resource': 20+i}], 'pso': {'shader_hashes': {'CS': f'h{i}'}}} for i in range(1, 6)]
    runs = identify_runs(survey)
    need(len(runs) == 1 and runs[0]['dispatches'] == 5, 'five-dispatch contiguous synthetic NRD topology')
    need(runs[0]['method_hypothesis'] == 'REBLUR_event_label', 'method stays explicitly a hypothesis')
    row = {'source': 'synthetic_only_not_game_evidence', 'checks_passed': checks, 'cases': cases,
           'negative_best_holdout_relative_l1': pairs[0]['holdout']['mean_relative_l1'],
           'seconds': time.perf_counter()-started, 'peak_working_set_bytes': peak_bytes()}
    output.mkdir(parents=True, exist_ok=True)
    (output/'test-result.json').write_text(json.dumps(row, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(row), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('F:/FSRD/frame_survey/synthetic'))
    run(parser.parse_args().output)
