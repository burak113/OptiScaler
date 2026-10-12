"""CPU invariants for the offline RR scale experiment; no shipping feature claim."""
import numpy as np
from fsrd_rr_scale_reference import down_half

def run():
    depth=np.ones((2,2),np.float32)*10
    packed=np.full((2,2),512|(512<<10),np.uint32)
    motion=np.zeros((2,2,4),np.float16);motion[...,3]=1
    q=np.repeat(np.asarray([[25,76],[178,229]],np.uint8)[...,None],4,-1)
    u=np.zeros((2,2,4),np.float16);u[...,:3]=1/(q[...,:3].astype(np.float32)/255)
    energy=down_half(depth,packed,motion,q,q,u,u)
    legacy=down_half(depth,packed,motion,q,q,u,u,energy=False,material_priority=False,roughness_squared=False)
    mean_raw=(u[...,:3].astype(np.float32)*(q[...,:3]/255)).mean((0,1))
    mean_q=(q[...,:3]/255).mean((0,1))
    assert np.max(np.abs(energy[5][0,0,:3].astype(np.float32)*mean_q-mean_raw))<1e-3
    assert np.min(legacy[5][0,0,:3]*mean_q-mean_raw)>.9
    P=packed|np.asarray([[0,3],[1,2]],np.uint32)<<30
    chosen=down_half(depth,P,motion,q,q,u,u)[1]
    assert (chosen[0,0]>>30)==1
    rough=packed|np.asarray([[0,0],[1023,1023]],np.uint32)<<20
    r=down_half(depth,rough,motion,q,q,u,u)[1]
    assert abs(((r[0,0]>>20)&1023)/1023-np.sqrt(.5))<1/1023
    assert energy[0].shape==(1,1) and energy[2].shape==(1,1,4)
    assert np.all(np.isfinite(energy[5])) and np.all(np.isfinite(energy[6]))
    print('6 offline RR downsample invariants PASS; no production scale option implemented')

if __name__=='__main__':run()
