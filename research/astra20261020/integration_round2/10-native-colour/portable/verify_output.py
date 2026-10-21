"""Independent output invariants shared by fixture replay and bad controls."""
import numpy as np
from packed_model import unpack


def verify(case, returned, *, rgb_ulp=1):
    expected=case['packed']['expected_output']
    initial=case['packed']['initial_output']
    layout=case['layouts'][3]
    assert returned.dtype==np.uint8 and returned.shape==expected.shape,'buffer capacity mismatch'
    actual=unpack(returned,layout)
    selected=case['selected'].view(np.uint16)
    oracle=case['output']
    assert np.array_equal(actual[...,3],selected[...,3]),'native alpha words changed'
    # Freeze the writable-domain mask from ORIGINAL inputs, never output/diagnostic.
    writable=np.zeros(selected.shape[:2],bool)
    h,w=case['identity'].active_height,case['identity'].active_width
    raw=case['raw'][:h,:w]
    source=case['source'][:h,:w]
    z=case['depth'][:h,:w]
    writable[:h,:w]=(np.all(raw.view(np.uint16)==selected[:h,:w],axis=-1) &
        (case['authority'][:h,:w]==1) & (case['support'][:h,:w]==1) &
        np.all(np.isfinite(raw[...,:3]) & (raw[...,:3]>=0),axis=-1) &
        np.all(np.isfinite(source[...,:3]) & (source[...,:3]>=0),axis=-1) & np.isfinite(z) & (z!=0))
    if case['decision']!='Ready': writable[:]=False
    assert np.array_equal(actual[~writable],selected[~writable]),'protected/invalid pixels changed'
    guard=np.ones(layout.size,bool)
    for y in range(case['identity'].active_height):
        start=layout.offset+y*layout.row_pitch
        guard[start:start+case['identity'].active_width*8]=False
    assert np.array_equal(returned[guard],initial[guard]),'padding/canary/inactive extent changed'
    differences=np.abs(actual[...,:3].astype(np.int32)-oracle[...,:3].astype(np.int32))
    assert np.all(differences[writable]<=rgb_ulp),'eligible RGB differs beyond half-ULP gate'
    # This is an ON test's expected non-vacuity assertion, never a quality mask.
    if np.any(oracle!=selected):
        assert np.any(actual[writable]!=selected[writable]),'non-vacuous ON canary is identity'
    else:
        assert np.array_equal(returned,initial),'identity case changed bytes'
    return dict(alpha_exact=True,protected_exact=True,padding_exact=True,
                maximum_rgb_half_ulp=int(differences[writable].max(initial=0)),
                changed_pixels=int(np.count_nonzero(np.any(actual!=selected,axis=-1))))
