"""Deliberately wrong implementations: each named command MUST exit1.

These red runs prove relevant invariants reject the mutation. The acceptance
runner records actual exit1 as an expected rejection, never a successful model.
"""
import argparse
import numpy as np
from numerical_contract.sampling import sample_bilinear, sample_point
from numerical_contract.storage import store_fp16


def run(name):
    if name=='wrong_uv':
        y,x=np.indices((11,17),dtype=np.float32);tex=x+10*y
        wrong_uv=np.array([(3+.5)/13,(2+.5)/7],np.float32)
        value=sample_bilinear(tex,wrong_uv,mode='source').require_supported()
        np.testing.assert_equal(value,np.float32(23))
    elif name=='nearest':
        tex=np.array([[0,1],[2,3]],np.float32)
        value=sample_point(tex,np.array([.375,.375]),mode='source').require_supported()
        np.testing.assert_equal(value,np.float32(.75))
    elif name=='old_normal':
        value=store_fp16(np.float32(2049/65535),rounding='rtz')
        restored=int(np.floor(value*np.float32(65535)+np.float32(.5)))
        assert restored==2049,'old normalized16 payload lost code bits'
    elif name=='missing_high':
        exact=262145*16*65536
        assert (exact&0xffffffff)==exact,'missing high word loses64 natural carries'
    elif name=='premature_rounding':
        accumulator=np.float32(1)
        for _ in range(3):accumulator=store_fp16(accumulator+np.float32(2**-11),rounding='rtz')
        output=store_fp16(accumulator/np.float32(4),rounding='rtz')
        np.testing.assert_equal(output,np.float32(.250244140625))
    else:raise ValueError(name)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mutant',choices=['wrong_uv','nearest','old_normal','missing_high','premature_rounding'])
    run(parser.parse_args().mutant)
