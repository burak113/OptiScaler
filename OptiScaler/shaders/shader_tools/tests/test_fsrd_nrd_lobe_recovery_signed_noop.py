"""CPU signed no-correction contracts; no compiler or GPU execution."""
from dataclasses import replace
import unittest
import numpy as np
from fsrd_nrd_lobe_reference_prototype import LobeReferenceRecovery,ReferenceSettings,finish


def signed_packet(width=33,height=29,roughness=123):
    yy,xx=np.mgrid[:height,:width]
    rr=np.full((height,width,4),.5,'<f2')
    rr[...,0]=np.asarray([-.001,-0.0,0.0],'<f2')[xx%3]
    rr[...,2]=np.where((xx+yy)%2,-0.0,0.0).astype('<f2')
    rr[...,3]=np.asarray([-0.0,0.0,-.001,7],'<f2')[xx%4]
    raw=np.full_like(rr,.5);raw[...,:3]+=np.where((xx+yy)%2,.0625,-.0625)[...,None].astype('<f2');raw[...,3]=9
    depth=np.full((height,width),-8,'<f4')
    normal=np.full((height,width),512|(512<<10)|(roughness<<20),'<u4')
    motion=np.zeros((height,width,4),'<f2');motion[...,3]=1
    return raw,rr,depth,normal,motion


class SignedNoCorrection(unittest.TestCase):
    def test_anchor_cannot_manufacture_a_zero_correction(self):
        rr=np.array([[[-.001,-0.0,0.0],[.5,.5,.5]]],np.float32)
        for supported in (False,True):
            value,_=finish(rr,np.zeros_like(rr),np.full(rr.shape[:2],supported),ReferenceSettings(bound_projection='local_anchor'))
            np.testing.assert_array_equal(value,np.zeros_like(value))

    def test_cold_zero_roughness_and_strength_zero_preserve_all_bits(self):
        for storage in ('fp32','mixed'):
            for rough,zero_strength,count in ((123,False,7),(0,False,24),(123,True,24)):
                packet=signed_packet(roughness=rough)
                operator=LobeReferenceRecovery(ReferenceSettings(bound_projection='local_anchor',texture_storage=storage,strength=0 if zero_strength else 1))
                for frame in range(count):
                    value=operator.step(*packet,frame)
                    np.testing.assert_array_equal(value.view('<u2'),packet[1].view('<u2'))

    def test_mature_disable_and_zero_channels_remain_exact(self):
        for storage in ('fp32','mixed'):
            packet=signed_packet()
            operator=LobeReferenceRecovery(ReferenceSettings(bound_projection='local_anchor',texture_storage=storage))
            for frame in range(16):
                value=operator.step(*packet,frame)
                rr=packet[1]
                fixed=rr[...,:3]<=0
                np.testing.assert_array_equal(value[...,:3].view('<u2')[fixed],rr[...,:3].view('<u2')[fixed])
                np.testing.assert_array_equal(value[...,3].view('<u2'),rr[...,3].view('<u2'))
            operator.settings=replace(operator.settings,strength=0)
            np.testing.assert_array_equal(operator.step(*packet,16).view('<u2'),packet[1].view('<u2'))


if __name__=='__main__':unittest.main()
