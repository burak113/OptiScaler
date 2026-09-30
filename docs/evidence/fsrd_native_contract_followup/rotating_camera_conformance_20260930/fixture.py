"""Physical planar rotating-camera conversion fixture, CPU only.

Matrices are contiguous row-major for row-vector multiplication. The converter's
default column-major HLSL reads these bytes as transpose and mul(M,column) thus
equals row@M. No GPU/native imports or dispatches occur in this module.
"""
import math
import numpy as np

def perspective(w=128,h=80,near=.1,far=1000.):
    sy=1/math.tan(math.pi/6);sx=sy/(w/h)
    return np.array([[sx,0,0,0],[0,sy,0,0],[0,0,far/(far-near),1],[0,0,-near*far/(far-near),0]],float)

def rotation_y(theta=.02):
    c,s=math.cos(theta),math.sin(theta)
    return np.array([[c,0,-s,0],[0,1,0,0],[s,0,c,0],[0,0,0,1]],float)

def rgba(rgb,alpha=1.):
    rgb=np.asarray(rgb,np.float32)
    return np.concatenate((rgb,np.full((*rgb.shape[:-1],1),alpha,np.float32)),axis=-1)

def project(xyz,projection):
    clip=np.concatenate((xyz,np.ones((*xyz.shape[:-1],1))),-1)@projection
    ndc=clip[...,:3]/clip[...,3:4]
    return np.stack((ndc[...,0]*.5+.5,.5-ndc[...,1]*.5),-1),ndc[...,2]

def reconstruct(uv,depth,inv_projection,linear=True):
    z=np.full(uv.shape[:-1],.5) if linear else depth
    clip=np.stack((2*uv[...,0]-1,1-2*uv[...,1],z,np.ones_like(z)),-1)
    point=clip@inv_projection
    safe_w=np.where(point[...,3]<0,np.minimum(point[...,3],-1e-6),np.maximum(point[...,3],1e-6))
    xyz=point[...,:3]/safe_w[...,None]
    if linear:
        z=np.clip(np.abs(depth),.1,1000.)
        safe_z=np.where(xyz[...,2]<0,np.minimum(xyz[...,2],-1e-6),np.maximum(xyz[...,2],1e-6))
        xyz*=z[...,None]/safe_z[...,None];xyz[...,2]=z
    return xyz

def oct_encode(normal):
    p=normal/np.abs(normal).sum(-1,keepdims=True)
    xy=p[...,:2].copy();k=np.where(xy>0,1.,-1.)
    xy=np.where((p[...,2]<0)[...,None],(1-np.abs(xy[...,::-1]))*k,xy)
    return xy*.5+.5

def make_fixture(roughness=.1,matched_projection=True,theta=.02,current_jitter=(0.,0.),previous_jitter=(0.,0.),jittered_motion=False,hardware_depth=False,packed_roughness=False):
    w,h=128,80;y,x=np.indices((h,w));j=np.asarray(current_jitter,float)
    uv=np.stack(((x+.5-j[0])/w,(y+.5-j[1])/h),-1)
    # First quantize every matrix to actual cbuffer/native float32 bytes, then
    # use those consumed values for both analytic and shader expectations.
    projection=perspective(w,h).astype(np.float32)
    inverse=np.linalg.inv(projection.astype(float)).astype(np.float32)
    previous=rotation_y(theta).astype(np.float32)
    z=np.full((h,w),10.)
    # Independent pinhole construction, not inverse-project implementation.
    xyz=np.stack(((2*uv[...,0]-1)*10/projection[0,0],(1-2*uv[...,1])*10/projection[1,1],z),-1)
    world=np.concatenate((xyz,np.ones((h,w,1))),-1)
    prev_xyz=(world@previous)[...,:3]
    previous_uv,_=project(prev_xyz,projection)
    _,hardware=project(xyz,projection)
    motion=previous_uv-uv
    if jittered_motion:motion+=(np.asarray(previous_jitter)-j)/[w,h]
    flags=(0 if hardware_depth else 2)|32|2048|(256 if jittered_motion else 0)|(4 if packed_roughness else 0)
    normal=np.broadcast_to(np.array([.2,.1,-math.sqrt(.95)]),(h,w,3)).copy()
    nalpha=roughness if packed_roughness else 1.
    supplied_inverse=inverse if matched_projection else np.eye(4,dtype=np.float32)
    shader_xyz=reconstruct(uv,hardware if hardware_depth else z,supplied_inverse,not hardware_depth)
    shader_prev=(np.concatenate((shader_xyz,np.ones((h,w,1))),-1)@previous)[...,:3]
    expected_mvz=prev_xyz[...,2]-xyz[...,2]
    shader_mvz=shader_prev[...,2]-shader_xyz[...,2]
    canonical_xy=motion.copy()
    if jittered_motion:canonical_xy-=(np.asarray(previous_jitter)-j)/[w,h]
    shader_motion=np.concatenate((canonical_xy,shader_mvz[...,None],np.ones((h,w,1))),-1)
    expected_normals=np.concatenate((oct_encode(normal),np.full((h,w,1),roughness),np.zeros((h,w,1))),-1)
    # .1/.55 are deliberately outside the specularTracking transition band.
    tracking=1. if roughness<=.15 else (0. if roughness>=.30 else None)
    assert tracking is not None
    return dict(raw=rgba(np.broadcast_to([.4,.35,.3],(h,w,3))),
        diff=rgba(np.broadcast_to([.35,.3,.25],(h,w,3))),spec=rgba(np.broadcast_to([.06,.07,.08],(h,w,3))),
        depth=np.asarray(hardware if hardware_depth else z,np.float32),normals=rgba(normal,nalpha),roughness=np.full((h,w),roughness,np.float32),
        motion=rgba(np.concatenate((motion,np.zeros((h,w,1))),-1)),
        current_uv=uv,previous_uv=previous_uv,world_xyz=xyz,previous_xyz=prev_xyz,
        expected_physical_mvz=expected_mvz,expected_converter_motion_float32=shader_motion.astype(np.float32),
        expected_converter_motion_fp16=shader_motion.astype(np.float16),expected_normal_before_storage=expected_normals,
        expected_specular_alpha=10.*tracking,expected_diffuse_alpha=65504.,
        matched_projection=matched_projection,theta=theta,
        overrides=dict(InvViewMatrix=np.eye(4,dtype=np.float32).ravel().tolist(),InvProjMatrix=supplied_inverse.ravel().tolist(),PrevViewMatrix=previous.ravel().tolist(),
            NearPlane=.1,FarPlane=1000.,Flags=flags,JitterOffsets=[*current_jitter,*previous_jitter],MotionTransform=[1,1,0,0],
            DiffuseHitDistanceMode=0),
        projection=projection,previous_view=previous,resources={})
