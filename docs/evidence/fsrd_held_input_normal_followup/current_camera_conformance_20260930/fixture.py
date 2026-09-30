"""CPU-only physical world-plane fixtures for nonidentity current/previous view.

All matrix objects supplied to the shader/native camera contract are float32,
contiguous row-major for row-vector multiplication. No GPU imports or calls.
"""
import math
import numpy as np

W,H=128,80
CURRENT_POSITION=np.array([.3,.1,-.2],float)
PREVIOUS_POSITION=np.array([.29,.1,-.2],float)

def rotation_y(theta):
    c,s=math.cos(theta),math.sin(theta)
    return np.array([[c,0,-s],[0,1,0],[s,0,c]],float)

def view(position,theta):
    r=rotation_y(theta);v=np.eye(4);v[:3,:3]=r;v[3,:3]=-np.asarray(position)@r
    return v.astype(np.float32)

def projection():
    sy=1/math.tan(math.pi/6);sx=sy/(W/H);near,far=.1,1000.
    return np.array([[sx,0,0,0],[0,sy,0,0],[0,0,far/(far-near),1],[0,0,-near*far/(far-near),0]],np.float32)

def homogeneous(xyz):return np.concatenate((xyz,np.ones((*xyz.shape[:-1],1))),-1)
def normalized(v):return v/np.linalg.norm(v,axis=-1,keepdims=True)
def rgba(rgb,alpha=1):
    rgb=np.asarray(rgb,np.float32)
    return np.concatenate((rgb,np.full((*rgb.shape[:-1],1),alpha,np.float32)),axis=-1)

def project(point,p):
    clip=homogeneous(point)@p.astype(float);ndc=clip[...,:3]/clip[...,3:4]
    return np.stack((ndc[...,0]*.5+.5,.5-ndc[...,1]*.5),-1),ndc[...,2]

def reconstruct(uv,depth,inv,linear):
    depth=np.asarray(depth,float)
    z=np.full(depth.shape,.5) if linear else depth
    clip=np.stack((2*uv[...,0]-1,1-2*uv[...,1],z,np.ones_like(z)),-1)
    point=clip@inv.astype(float);xyz=point[...,:3]/point[...,3:4]
    canonical_z=np.clip(np.abs(depth if linear else xyz[...,2]),.1,1000.)
    xyz*=canonical_z[...,None]/xyz[...,2:3];xyz[...,2]=canonical_z
    return xyz

def oct_encode(normal):
    p=normal/np.abs(normal).sum(-1,keepdims=True);xy=p[...,:2]
    xy=np.where((p[...,2]<0)[...,None],(1-np.abs(xy[...,::-1]))*np.where(xy>0,1.,-1.),xy)
    return xy*.5+.5

def oct_decode(uv):
    xy=np.asarray(uv,float)*2-1
    n=np.concatenate((xy,1-np.abs(xy).sum(-1,keepdims=True)),-1)
    t=np.maximum(-n[...,2:3],0)
    n[...,:2]+=np.where(n[...,:2]>=0,-t,t)
    return normalized(n)

def make_fixture(depth_mode='linear',normal_space='world'):
    assert depth_mode in ('linear','hardware') and normal_space in ('world','view')
    current_view=view(CURRENT_POSITION,.17);previous_view=view(PREVIOUS_POSITION,.15)
    p=projection();inverse_p=np.linalg.inv(p.astype(float)).astype(np.float32)
    inverse_v=np.linalg.inv(current_view.astype(float)).astype(np.float32)
    y,x=np.indices((H,W));uv=np.stack(((x+.5)/W,(y+.5)/H),-1)
    ray_view=np.stack(((2*uv[...,0]-1)/float(p[0,0]),(1-2*uv[...,1])/float(p[1,1]),np.ones((H,W))),-1)
    # Independent pinhole/world-plane intersection uses exact inverse of the
    # consumed current rotation, not the shader's quantized inverse projection.
    inverse_rotation=np.linalg.inv(current_view[:3,:3].astype(float))
    origin=-current_view[3,:3].astype(float)@inverse_rotation
    ray_world=ray_view@inverse_rotation
    t=(10-origin[2])/ray_world[...,2]
    assert np.all(t>0)
    world=origin+ray_world*t[...,None];world[...,2]=10
    current=(homogeneous(world)@current_view.astype(float))[...,:3]
    previous=(homogeneous(world)@previous_view.astype(float))[...,:3]
    current_uv,hardware_depth=project(current,p);previous_uv,_=project(previous,p)
    physical_mvz=previous[...,2]-current[...,2]
    supplied_depth=(current[...,2] if depth_mode=='linear' else hardware_depth).astype(np.float32)
    world_normal=np.array([0.,0.,-1.]);view_normal=normalized(world_normal@current_view[:3,:3].astype(float))
    normal_value=world_normal if normal_space=='world' else view_normal
    normals=rgba(np.broadcast_to(normal_value,(H,W,3)))
    # The upload path consumes FP16 normal/MV resources and R32 depth. Every
    # shader reference accounts for these input conversions before prediction.
    consumed_normal=normals[...,:3].astype(np.float16).astype(float)
    shader_world_normal=normalized(consumed_normal if normal_space=='world' else consumed_normal@inverse_v[:3,:3].astype(float))
    oct_uv=oct_encode(shader_world_normal)
    pre_storage_normals=np.concatenate((oct_uv,np.full((H,W,1),.1),np.zeros((H,W,1))),-1)
    half_normals=pre_storage_normals.astype(np.float16).astype(float)
    quant=np.rint(np.clip(half_normals,0,1)*[1023,1023,1023,3])/[1023,1023,1023,3]
    motion=rgba(np.concatenate((previous_uv-current_uv,np.zeros((H,W,1))),-1))
    shader_current=reconstruct(uv,supplied_depth,inverse_p,depth_mode=='linear')
    shader_world=homogeneous(shader_current)@inverse_v.astype(float)
    shader_previous=shader_world@previous_view.astype(float)
    shader_mvz=shader_previous[...,2]-shader_current[...,2]
    expected_motion=np.concatenate((motion[...,:2].astype(np.float16).astype(float),shader_mvz[...,None],np.ones((H,W,1))),-1)
    flags=32|(2 if depth_mode=='linear' else 0)|(2048 if normal_space=='view' else 0)
    return dict(raw=rgba(np.broadcast_to([.4,.35,.3],(H,W,3))),diff=rgba(np.broadcast_to([.35,.3,.25],(H,W,3))),
        spec=rgba(np.broadcast_to([.06,.07,.08],(H,W,3))),depth=supplied_depth,normals=normals,roughness=np.full((H,W),.1,np.float32),motion=motion,
        world_points=world,current_view_points=current,previous_view_points=previous,current_uv=current_uv,previous_uv=previous_uv,
        current_linear_depth=current[...,2],physical_mvz=physical_mvz,world_normal=world_normal,view_normal=view_normal,
        expected_converter_world_normal=shader_world_normal,expected_normal_before_storage=pre_storage_normals,
        expected_normal_R10_decoded=quant.astype(np.float32),expected_world_normal_after_R10=oct_decode(quant[...,:2]),
        expected_converter_motion_float32=expected_motion.astype(np.float32),expected_converter_motion_fp16=expected_motion.astype(np.float16),
        expected_specular_alpha_fp16=shader_current[...,2].astype(np.float16),expected_diffuse_alpha=65504.,
        current_view_matrix=current_view,previous_view_matrix=previous_view,inverse_view_matrix=inverse_v,projection_matrix=p,inverse_projection_matrix=inverse_p,
        depth_mode=depth_mode,normal_space=normal_space,
        overrides=dict(InvViewMatrix=inverse_v.ravel().tolist(),InvProjMatrix=inverse_p.ravel().tolist(),PrevViewMatrix=previous_view.ravel().tolist(),
            NearPlane=.1,FarPlane=1000.,Flags=flags,JitterOffsets=[0.,0.,0.,0.],MotionTransform=[1.,1.,0.,0.],DiffuseHitDistanceMode=0))
