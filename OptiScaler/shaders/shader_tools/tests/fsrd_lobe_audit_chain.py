"""Audit-only replay of production RecoveryLobe host order on recorded RR lobes.

The crop has no off-ROI history. No new denoiser or recovery algorithm is used.
"""
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t


def build_chain(frames, directory, precompile, strength=(1, 1)):
    h, w = frames[0]['depth'].shape
    sizes = [(w, h)]
    for _ in range(6):
        sizes.append(tuple((v+1)//2 for v in sizes[-1]))
    job = t.create_chain(directory)
    def tex(name, size, data=None, fmt=10, writable=False, readback=False):
        job.texture(name, data, format=fmt, size=size, writable=writable, readback=readback)
        return name
    tiny = tex('tiny', (1,1), np.zeros((1,1,4),np.float16))
    for bank in (0,1):
        for name in ('s','d','g','grad'):
            tex(f'{name}{bank}',sizes[0],np.zeros((h,w,4),np.float16),writable=True)
        for level in range(6):
            ww,hh=sizes[level]
            tex(f'noise{bank}_{level}',sizes[level],np.zeros((hh,ww,4),np.float16),writable=True)
    for level, size in enumerate(sizes):
        for name in ('A','B','C'):
            tex(f'{name}{level}',size,writable=True)
        if level<6:
            for name in ('corrS','corrD'):
                tex(f'{name}{level}',size,writable=True)
    tex('dummyS',(1,1),writable=True);tex('dummyD',(1,1),writable=True);tex('dummyColor',(1,1),writable=True)
    names=[]
    for i, f in enumerate(frames):
        n=lambda key:f'f{i}_{key}'
        for key,fmt in [('U',10),('V',10),('rrs',10),('rrd',10),('qs',28),('qd',28),('skip',10),('packed',24),('depth',41),('motion',10)]:
            tex(n(key),sizes[0],f[key],fmt)
        tex(n('composed'),sizes[0],f['composed'])
        tex(n('output'),sizes[0],writable=True,readback=True);names.append(n('output'))
        flags = int(i>0 and not f.get('reset',False))
        bank=i%2;prev=1-bank
        cb=dict(DstTexSize=[w,h,1/w,1/h],LevelSize=[w,h,w,h],Strength=[*strength,0,0],
                Jitter=f['jitter'],Modulation=[1,1],Response=.03,Threshold=3,MatureAge=8,Flags=flags,
                Level=0,FrameIndex=i,Debug=0,GradientAge=8,Blend=[0,4,0,0])
        shader=lambda s:Path(precompile)/(s+'_Shader.cso')
        job.compute(n('Accumulate'),shader('FSRDRecoveryLobeAccumulate'),t.constants('FSRDRecoveryLobeAccumulate',cb),
                    [n(k) for k in ('U','V','rrs','rrd')]+[tiny]+[n(k) for k in ('qs','qd','depth','packed','motion','skip')]+
                    [f's{prev}',f'd{prev}',f'g{prev}',f'grad{prev}'],
                    [f's{bank}',f'd{bank}',f'g{bank}','A0','B0','C0',f'grad{bank}'],groups=((w+7)//8,(h+7)//8,1))
        for level in range(1,7):
            ww,hh=sizes[level];pw,ph=sizes[level-1]
            c=dict(cb,Level=level,LevelSize=[ww,hh,pw,ph])
            job.compute(n(f'Down{level}'),shader('FSRDRecoveryLobeDown'),t.constants('FSRDRecoveryLobeDown',c),
                        [f'{k}{level-1}' for k in ('A','B','C')],[f'{k}{level}' for k in ('A','B','C')],
                        groups=((ww+7)//8,(hh+7)//8,1))
        for level in range(5,-1,-1):
            ww,hh=sizes[level];cw,ch=sizes[level+1];last=level==0;coarsest=level==5
            c=dict(cb,Level=level,LevelSize=[ww,hh,cw,ch],Flags=flags|(8 if coarsest else 0)|(16 if last else 0))
            job.compute(n(f'Band{level}'),shader('FSRDRecoveryLobeBand'),t.constants('FSRDRecoveryLobeBand',c),
                        [f'{k}{level}' for k in ('A','B','C')]+[f'{k}{level+1}' for k in ('A','B')]+
                        ([tiny,tiny] if coarsest else [f'corrS{level+1}',f'corrD{level+1}'])+
                        [f'noise{prev}_{level}',n('motion'),n('composed'),n('qs'),n('qd'),n('skip'),n('rrs'),n('rrd'),tiny],
                        ['dummyS' if last else f'corrS{level}','dummyD' if last else f'corrD{level}',
                         f'noise{bank}_{level}',n('output') if last else 'dummyColor'],groups=((ww+7)//8,(hh+7)//8,1))
    return job,names
