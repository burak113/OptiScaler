"""Inventory published capture metadata and exact replay/comparison boundaries.

This script never reads a binary pixel payload. Native FrameSurvey ordinals are
command-list recordings, not a temporal sequence. Older GAME_TRACE U/V captures
can replay the combined-color path on identical inputs; they are not a paired
native NRD/bridge recording or a clean reference.
"""
from pathlib import Path, PurePosixPath
import argparse
import gc
import hashlib
import json
import math
import os
import re
import time

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CAPTURE_ROOT = Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE')
COMBINED_ROLES = {'U', 'V', 'packed', 'depth', 'motion', 'Qs', 'Qd', 'Skip', 'current_output'}
CAMERA_FIELDS = {'view', 'projection', 'jitter', 'camera_delta', 'motion_vector_scale', 'depth_bounds'}


def safe_path(value):
    path = Path(value).resolve()
    if any(part.lower() == 'reserve_data' for part in path.parts):
        raise ValueError('reserve_data is excluded')
    return path


def finite_vector(value, count):
    return (isinstance(value, list) and len(value) == count
            and all(type(item) in (int, float) and math.isfinite(item) for item in value))


def published_frames(document):
    bound = document.get('manifest_published_frames')
    frames = document.get('frames')
    if type(bound) is not int or bound < 0 or not isinstance(frames, list) or bound > len(frames):
        return [], 'missing_or_invalid_manifest_published_frames'
    if bound == 0:
        return [], 'zero_published_frames'
    return frames[:bound], None


def image_roles(frame):
    images = frame.get('images', [])
    if not isinstance(images, list):
        return set()
    return {item['name'] for item in images if isinstance(item, dict) and isinstance(item.get('name'), str)}


def shader_roles():
    text = (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdDiscovery.h').read_text()
    return dict(re.findall(r'\{"([0-9a-f]{64})",Role::([A-Za-z0-9_]+)\}', text))


def camera_coverage(frames):
    result = {'complete_frames': 0, 'unique_view_matrices': 0, 'unique_projection_matrices': 0,
              'unique_jitters': 0, 'nonzero_camera_delta_frames': 0, 'captured_reset_frames': 0}
    views, projections, jitters = set(), set(), set()
    for frame in frames:
        c = frame.get('controls', {})
        if not isinstance(c, dict):
            continue
        complete = (finite_vector(c.get('view'), 16) and finite_vector(c.get('projection'), 16)
                    and finite_vector(c.get('jitter'), 2) and finite_vector(c.get('camera_delta'), 3)
                    and finite_vector(c.get('depth_bounds'), 2)
                    and (finite_vector(c.get('motion_vector_scale'), 2) or finite_vector(c.get('motion_vector_scale'), 3)))
        result['complete_frames'] += int(complete)
        if complete:
            views.add(tuple(c['view'])); projections.add(tuple(c['projection'])); jitters.add(tuple(c['jitter']))
            result['nonzero_camera_delta_frames'] += int(any(c['camera_delta']))
        result['captured_reset_frames'] += int(frame.get('reset') is True)
    result.update(unique_view_matrices=len(views), unique_projection_matrices=len(projections), unique_jitters=len(jitters))
    return result


def native_stage_coverage(document, frames, roles):
    # Only metadata belonging to published command-list payload ordinals is considered.
    list_ids = {frame.get('list_id') for frame in frames}
    stages = []
    for commands in document.get('command_lists', []):
        if not isinstance(commands, dict) or commands.get('id') not in list_ids:
            continue
        for item in commands.get('passes', []):
            shader = item.get('pso', {}).get('shader_hashes', {}).get('CS')
            role = roles.get(shader)
            if role not in ('Recon', 'Temporal', 'Consumer'):
                continue
            stages.append({'list_id': commands['id'], 'local_pass': item.get('local_pass'), 'role': role,
                           'shader_sha256': shader, 'reads': len(item.get('reads', [])),
                           'writes': len(item.get('writes', [])), 'unresolved': len(item.get('unresolved', []))})
    return stages


def payload_metadata_coverage(folder, frames):
    present = missing = unsafe = 0
    for ordinal, frame in enumerate(frames):
        for item in frame.get('images', []):
            if not isinstance(item, dict):
                unsafe += 1; continue
            spelling = item.get('file')
            if not isinstance(spelling, str):
                unsafe += 1; continue
            relative = PurePosixPath(spelling)
            if relative.is_absolute() or '..' in relative.parts or len(relative.parts) < 3 or relative.parts[:2] != ('frames', str(ordinal)):
                unsafe += 1; continue
            path = safe_path(folder.joinpath(*relative.parts))
            if not path.is_relative_to(folder):
                unsafe += 1; continue
            # Stat only: no binary arrays, no payload hashing or decode here.
            if path.is_file() and path.stat().st_size == item.get('bytes'):
                present += 1
            else:
                missing += 1
    return {'present_expected_size': present, 'missing_or_wrong_size': missing, 'unsafe_paths': unsafe}


def inspect_capture(path, roles):
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('metadata exceeds 128 MiB inspection bound')
    raw = path.read_bytes()
    document = json.loads(raw)
    reference = document.get('reference')
    clean = isinstance(reference, dict) and reference.get('available') is True
    frames, rejection = published_frames(document)
    result = {'capture': str(path.parent), 'metadata_sha256': hashlib.sha256(raw).hexdigest(),
              'metadata_bytes': len(raw), 'schema': document.get('schema'),
              'source': document.get('source'), 'published_payload_ordinals': len(frames),
              'publication_rejection': rejection, 'render_extent': document.get('render_extent'),
              'roi': document.get('roi'), 'build_identity': document.get('build_identity'),
              'settings_sha256': document.get('settings_sha256'),
              'clean_reference_available': clean,
              'binary_pixels_loaded': False}
    if not frames:
        result.update(temporal_native_nrd_replay_ready=False, combined_color_same_input_replay_ready=False)
        return result
    all_roles = sorted(set().union(*(image_roles(frame) for frame in frames)))
    camera = camera_coverage(frames)
    result.update(image_roles=all_roles, camera=camera,
                  payload_metadata=payload_metadata_coverage(path.parent, frames))
    if document.get('schema') == 'fsrd-frame-survey-v1':
        result.update(payload_ordinal_unit=document.get('payload_ordinal_unit'),
                      encoding_identification=document.get('encoding_identification'),
                      native_stages=native_stage_coverage(document, frames, roles),
                      native_b6_word303_captured=False, temporal_native_nrd_replay_ready=False,
                      combined_color_same_input_replay_ready=False,
                      limitation='Published command-list payloads lack a rendered-frame camera/jitter/native-b6 history contract.')
    else:
        complete = all(COMBINED_ROLES.issubset(image_roles(frame)) for frame in frames)
        ready = (document.get('schema') == 'fsrd-game-trace-v5' and complete
                 and camera['complete_frames'] == len(frames)
                 and not result['payload_metadata']['missing_or_wrong_size']
                 and not result['payload_metadata']['unsafe_paths'])
        result.update(payload_ordinal_unit='recorded_evaluation', combined_roles_every_frame=complete,
                      combined_color_same_input_replay_ready=ready, temporal_native_nrd_replay_ready=False,
                      limitation='Combined-color U/V path capture; no attested same-frame native NRD Recon/guides/Consumer b6 pair.')
    return result


def capture_paths(root):
    for folder, directories, files in os.walk(root):
        directories[:] = [name for name in directories if name.lower() != 'reserve_data']
        if 'capture.json' in files:
            yield safe_path(Path(folder) / 'capture.json')


def inventory(root):
    root = safe_path(root)
    roles = shader_roles()
    start = time.perf_counter()
    captures, errors = [], []
    for path in sorted(capture_paths(root)):
        try:
            captures.append(inspect_capture(path, roles))
        except (OSError, ValueError, TypeError, KeyError) as error:
            errors.append({'capture': str(path.parent), 'reason': str(error)})
        gc.collect()
    return {'source_root': str(root), 'base_source_commit': '6edf7d3d', 'metadata_only': True,
            'readiness_scope': 'Metadata eligibility only; verify payload hashes/formats, ROI and native control ABI before actual replay.',
            'publication_policy': 'Only payload ordinals < manifest_published_frames; no legacy exceptions.',
            'comparison_policy': 'Same immutable inputs and per-frame controls may pair replay candidates. Different game runs/scenes/settings never pair.',
            'captures': captures, 'errors': errors, 'elapsed_seconds': time.perf_counter() - start,
            'combined_same_input_replay_candidates': sum(item['combined_color_same_input_replay_ready'] for item in captures),
            'temporal_native_nrd_replay_candidates': sum(item['temporal_native_nrd_replay_ready'] for item in captures)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-root', type=Path, default=DEFAULT_CAPTURE_ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.capture_root)
    output = safe_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key not in ('captures', 'errors')}, indent=2))
    print('inspected_captures=' + str(len(result['captures'])) + ' metadata_errors=' + str(len(result['errors'])))


if __name__ == '__main__':
    main()
