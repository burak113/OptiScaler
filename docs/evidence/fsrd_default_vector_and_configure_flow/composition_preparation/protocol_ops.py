"""Draft CPU-only cohort bookkeeping. No shader, SDK, scoring or process calls."""
from pathlib import Path
import hashlib

LOGICAL_ORDER = ('Fork_r0', 'AMD_r0', 'AMD_r1', 'Fork_r1')
FRAMES = 64
WIDTH, HEIGHT = 128, 80
LOBE_BYTES = FRAMES * WIDTH * HEIGHT * 8

def sha(data):
    return hashlib.sha256(data).hexdigest()

def classify_full_rgba_traces(lobes):
    """Call only AFTER an independently pinned native completion gate.

    Equality is bytes across all 64 frames, both full RGBA FP16 lobes.
    Representatives are first occurrence in fixed native cohort order.
    Omitting composition is equivalence inheritance, never a measured call.
    """
    assert tuple(lobes) == LOGICAL_ORDER
    for arm in LOGICAL_ORDER:
        assert set(lobes[arm]) == {'diffuse', 'specular'}
        assert all(isinstance(v, bytes) and len(v) == LOBE_BYTES for v in lobes[arm].values())
    representatives, rows = [], {}
    for arm in LOGICAL_ORDER:
        representative = next((r for r in representatives if
            all(lobes[arm][l] == lobes[r][l] for l in ('diffuse', 'specular'))), None)
        if representative is None:
            representative = arm
            representatives.append(arm)
        rows[arm] = {
            'representative': representative,
            'new_actual_composition_planned': arm == representative,
            'omitted_metrics_policy': None if arm == representative else 'inherited_full64_RGBA_native_equivalence_not_new_composition_observations',
            'proof': {l: {'bytes': len(lobes[arm][l]), 'arm_sha256': sha(lobes[arm][l]),
                           'representative_sha256': sha(lobes[representative][l]),
                           'full64_RGBA_byte_equal': lobes[arm][l] == lobes[representative][l]}
                      for l in ('diffuse', 'specular')},
        }
    assert 1 <= len(representatives) <= 4
    return {'logical_order': list(LOGICAL_ORDER), 'representatives': representatives,
            'logical_rows': rows, 'unique_full64_trace_classes': len(representatives),
            'planned_helper_calls': 64 * len(representatives),
            'planned_output_files': 192 * len(representatives),
            'actual_helper_calls': 0, 'actual_composition_observations': 0}

def selected_job_order(representatives):
    assert representatives == [a for a in LOGICAL_ORDER if a in representatives]
    assert 1 <= len(representatives) <= 4
    return [(frame, arm) for frame in range(FRAMES) for arm in representatives]

def require_native_gate(gate, gate_identity, completed_native_identity):
    """Schema adapter placeholder: final accepted gate schema must be pinned, not guessed."""
    raise RuntimeError('Not finalized: actual four-context raw outputs, completed producer seal and independent native postgate must be pinned before implementing their exact schema adapter.')
