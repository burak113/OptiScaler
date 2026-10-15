"""CPU-only: exact half store ABI and already-retained native odd graph arrays.

No shader compiler, native process, GPU submission or output rewrite is used.
The original FP32 assertions are retained in the native fixture; this proves
the separate mixed storage model using its actual intermediate store points.
"""
import json
from pathlib import Path
import unittest
import numpy as np

from fsrd_nrd_lobe_reference_prototype import LobeReferenceRecovery,ReferenceSettings,half_store_rtz


class MixedStorageOracle(unittest.TestCase):
    def test_signed_normal_subnormal_ties_and_overflow_rtz(self):
        bits=np.arange(0x7bff,dtype=np.uint16)
        lower=bits.view(np.float16).astype(np.float32)
        upper=(bits+np.uint16(1)).view(np.float16).astype(np.float32)
        for fraction in (.25,.5,.75):
            value=lower+(upper-lower)*fraction
            np.testing.assert_array_equal(half_store_rtz(value),lower)
            np.testing.assert_array_equal(half_store_rtz(-value),-lower)
        np.testing.assert_array_equal(half_store_rtz(np.array([65504,65520,65536,-65504,-65520,-65536],np.float32)),
            np.array([65504,65504,65504,-65504,-65504,-65504],np.float32))
        self.assertEqual(half_store_rtz(np.array([-0.0],np.float32)).view(np.uint32)[0],0x80000000)

    def test_invalid_storage_fails_before_history(self):
        with self.assertRaises(ValueError):LobeReferenceRecovery(ReferenceSettings(texture_storage='half_noise'))

    def test_retained_native_odd_history_exact_mixed_oracle(self):
        root=Path('F:/FSRD/sol_batch/15b-inputs/tests')
        directory=root/'nrd-recovery-native-mixed-r1/recovery-graph/binary-odd-history'
        seal=json.loads((root/'nrd-recovery-native-r2/recovery-graph/result.json').read_bytes())
        self.assertTrue(seal['gpu_executed'])
        text=(directory/'native.native.log').read_text(encoding='utf-8')
        self.assertIn('validation_errors=0 validation_warnings=0',text)
        width,height=33,29
        yy,xx=np.mgrid[:height,:width]
        cpu={signal:LobeReferenceRecovery(ReferenceSettings(bound_projection='local_anchor',texture_storage='mixed')) for signal in ('spec','diff')}
        for index in range(24):
            rr=np.full((height,width,4),.5,'<f2');rr[...,3]=7
            raw=rr.copy()
            raw[...,:3]+=np.where((xx+yy)%2,.0625,-.0625)[...,None].astype('<f2')
            rr[...,:3]+=np.where((xx+yy)%2,.03125,-.03125)[...,None].astype('<f2')
            raw[...,3]=9
            depth=np.full((height,width),-8 if index<12 else -3,'<f4')
            normal=np.full((height,width),512|(512<<10)|((0 if index>=20 else 123)<<20),'<u4')
            motion=np.zeros((height,width,4),'<f2');motion[...,3]=1
            for signal in ('spec','diff'):
                expected=cpu[signal].step(raw,rr,depth,normal,motion,index,reset=index==0)
                paths=list(directory.glob('out_*_odd_frame%03d_%s.bin'%(index,signal)))
                self.assertEqual(len(paths),1)
                actual=np.fromfile(paths[0],'<f2').reshape(height,width,4)
                np.testing.assert_array_equal(actual[...,3],rr[...,3])
                self.assertTrue(np.isfinite(actual).all() and np.all(actual[...,:3]>=0))
                if index<7 or 12<=index<19 or index>=20:
                    np.testing.assert_array_equal(actual,rr)
                np.testing.assert_array_equal(actual,expected,err_msg='exact mixed texture storage index%d %s'%(index,signal))


if __name__=='__main__':unittest.main()
