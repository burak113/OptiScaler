"""Run: python test_fixture.py. CPU, NumPy only; never reads a game capture."""
import json
import numpy as np
from glass_fixture import analyze, policy_variants, HERE

rows,manifest=analyze()
for variant,metrics in rows.items():
    for key,value in metrics.items():
        expected=manifest['fixture_metrics'][variant][key]
        assert np.isclose(value,expected,rtol=5e-6,atol=2e-9),(variant,key,value,expected)
with np.load(HERE/'glass_crop.npz',allow_pickle=False) as f:
    raw=f['aligned_raw_spec_rgb']
    selected=np.bitwise_xor(raw.view('<u4'),f['aligned_selected_spec_rgb_xor']).view('<f4')
    variants=policy_variants(raw,selected)
    assert np.array_equal(variants['Glass Blend 0.5'],raw+np.float32(.5)*(selected-raw))
    assert np.array_equal(variants['Glass Blend 0.75'],raw+np.float32(.75)*(selected-raw))
    assert np.array_equal(variants['Glass RR'],raw)
    assert np.array_equal(variants['Glass Off (captured NZR)'],selected)
assert manifest['diffuse_equality']['differing_words']==0
assert manifest['diffuse_equality']['full_roi_fp16_words']==18874368
assert manifest['fixture_common_mask_pixels']<8048,'small crop must not claim the full-ROI mask'
assert not any(':' in item['file'] for item in manifest['source_payloads'].values())
print(json.dumps({'passed':True,'fixture_common_pixels':manifest['fixture_common_mask_pixels'],
                  'full_roi_evidence_is_separate':8048,'variants':rows},indent=2))
