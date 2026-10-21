"""Deliberate wrong implementations. EACH invocation must exit 1 by assertion.

The aggregate runner accepts the intended assertion text, never a crash/import
error. These controls establish test sensitivity, not candidate image quality.
"""
from dataclasses import replace
import argparse
import numpy as np
from fixtures import make_case
from packed_model import pack, process
from verify_output import verify


NAMES=('forced_off','alpha_repack','truthy_evidence','wrong_row_pitch','missing_prefill','raw_over_selection')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mutant',choices=NAMES)
    name=p.parse_args().mutant
    c=make_case()
    values=[c[key] for key in ('source','raw','selected','depth','normal','authority','support')]
    if name=='forced_off':
        out,_,_=process(*values,config=replace(c['config'],enabled=False),identity=c['identity'],evidence=c['evidence'])
        bad=pack(out,c['layouts'][3])
    elif name=='alpha_repack':
        out=c['output'].copy()
        alpha=out[...,3].view(np.float16)
        out[...,3]=np.where(np.isnan(alpha),np.float16(np.nan),np.abs(alpha)).astype(np.float16).view(np.uint16)
        bad=pack(out,c['layouts'][3])
    elif name=='truthy_evidence':
        values[-2]=(values[-2]!=0).astype(np.uint32)
        values[-1]=(values[-1]!=0).astype(np.uint32)
        out,_,_=process(*values,config=c['config'],identity=c['identity'],evidence=c['evidence'])
        bad=pack(out,c['layouts'][3])
    elif name=='wrong_row_pitch':
        bad=c['packed']['initial_output'].copy()
        h,w=c['identity'].active_height,c['identity'].active_width
        for y in range(h):
            start=c['layouts'][3].offset+y*w*8 # deliberately ignores row pitch
            bad[start:start+w*8]=c['output'][y,:w].view(np.uint8).ravel()
    elif name=='missing_prefill':
        bad=np.zeros_like(c['packed']['initial_output'])
        # Write all real texel words, leaving only the forgotten nontexel bytes
        # wrong. This isolates the complete-buffer prefill invariant from alpha.
        h,w=c['selected'].shape[:2]
        for y in range(h):
            start=c['layouts'][3].offset+y*c['layouts'][3].row_pitch
            bad[start:start+w*8]=c['output'][y,:w].view(np.uint8).ravel()
    else:
        wrong=c['selected'].copy()
        h,w=c['identity'].active_height,c['identity'].active_width
        # Preserve opaque selected alpha to isolate protected RGB selection.
        wrong[:h,:w,:3]=c['raw'][:h,:w,:3]
        values[2]=wrong
        out,_,_=process(*values,config=c['config'],identity=c['identity'],evidence=c['evidence'])
        bad=pack(out,c['layouts'][3])
    verify(c,bad)
    raise RuntimeError('known bad implementation escaped its invariant checks')


if __name__=='__main__':
    main()
