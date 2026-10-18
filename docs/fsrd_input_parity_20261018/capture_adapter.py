"""Both capture ingress formats to the SAME exact two-signal replay interface.

Native bridge MVs are provider-ready. Combined capture MVs are canonical; its
documented production jitter delta is added once. No inferred native NRD lobes
are manufactured from combined Color: this adapter uses the captured U/V.
"""
import json
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).with_name('reference')))
from cap2 import Cap as NativeCap, LUMA
from native_controls import controls as native_controls

class Cap(NativeCap):
    def __init__(self,cid):
        super().__init__(cid)
        if self.n is None or self.n<=0:
            raise ValueError('An explicit published prefix is required')
        self.combined='U' in {x['name'] for x in self.frames[0]['images']}
        if not self.combined:
            if any(frame.get('settings', {}).get('turn_colour', {}).get(key, False)
                   for frame in self.frames[:self.n] for key in ('enabled', 'brightness')):
                raise ValueError('Post-turn private RR input copies are absent from this capture')
            return
        self.original_frames=self.frames[:self.n]
        self.frames=[]
        aliases={'U':'input_specular','V':'input_diffuse','Qs':'input_specular_albedo',
                 'Qd':'input_diffuse_albedo','depth':'input_depth','packed':'input_normal_roughness','motion':'input_motion'}
        for original in self.original_frames:
            if original['settings']['signal_flags']!=34:
                raise ValueError('This controlled replay requires exactly DD+IS')
            fr=dict(original)
            fr['images']=[dict(row,name=aliases.get(row['name'],row['name'])) for row in original['images']]
            tuning=np.asarray(original['settings']['sdk_tuning'],np.float32).view(np.uint32).tolist()
            fr['settings']={'requested_values':tuning,'override_mask':63}
            self.frames.append(fr)

    def img(self,i,name,dt=np.float16,c=4):
        a=super().img(i,name,dt,c)
        if self.combined and name=='input_motion' and i:
            j=np.asarray(self.original_frames[i]['controls']['jitter'],np.float32)
            jp=np.asarray(self.original_frames[i-1]['controls']['jitter'],np.float32)
            a[...,:2]+=(jp-j)/np.array([self.RW,self.RH],np.float32)
        return a

    def camera(self,i):
        if not self.combined:
            return super().camera(i)
        fr=self.original_frames[i]['controls']
        view=np.asarray(fr['view'],np.float32).reshape(4,4).T
        projection=np.asarray(fr['projection'],np.float32).reshape(4,4).T
        position=np.linalg.inv(view.astype(np.float64))[:3,3]
        previous=position+np.asarray(fr['camera_delta'],np.float64)
        return position,previous,view,projection

    def rgb(self,i,kind):
        if not self.combined:
            return super().rgb(i,kind)
        if kind in ('rr','raw'):
            return self.img(i,'native_full1')[...,:3]
        return (self.img(i,'input_diffuse')[...,:3]*self.img(i,'input_diffuse_albedo',np.uint8)[...,:3]/255+
                self.img(i,'input_specular')[...,:3]*self.img(i,'input_specular_albedo',np.uint8)[...,:3]/255)

def controls(c,i):
    if not c.combined:
        return native_controls(c,i)
    original=c.original_frames[i]
    k=original['controls']
    a=np.zeros(46,np.float32);u=a.view(np.uint32)
    a[:3]=k['motion_vector_scale'];a[3:5]=k['jitter'];a[5:8]=k['camera_delta']
    a[8:24]=k['view'];a[24:40]=k['projection'];a[40:42]=k['depth_bounds']
    p=a[24:40].reshape(4,4).astype(np.float64)
    ax,bx=c.RW/c.W,(c.RW-2*c.X0-c.W)/c.W
    ay,by=c.RH/c.H,(c.H-c.RH+2*c.Y0)/c.H
    p[:,0]=ax*p[:,0]+bx*p[:,3];p[:,1]=ay*p[:,1]+by*p[:,3]
    a[24:40]=p.ravel();u[42:44]=[c.W,c.H]
    u[44]=original['native_frame_index'];u[45]=original['dispatch_flags']
    return a.tobytes()
