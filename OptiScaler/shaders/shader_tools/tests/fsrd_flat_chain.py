"""Actual Flat Detail production dispatch order for the typed GPU test runner."""
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t

SHADERS = ('FSRDFlatDetailClassify', 'FSRDFlatDetailSeed', 'FSRDFlatDetailRefine',
           'FSRDFlatTemporalLP', 'FSRDFlatTemporal', 'FSRDFlatTemporalStore', 'FSRDFlatDetailBase',
           'FSRDFlatDetailApply')


def rgba(rgb, alpha=0):
    return np.concatenate([np.asarray(rgb, np.float32),
                           np.full((*rgb.shape[:2], 1), alpha, np.float32)], -1)


def build_chain(frames, shaders, directory, *, temporal=True, initial_history=None,
                initial_count=0, initial_head=0, parameters=None, readback=True,
                cached_reference=False, fixed_baseline=False):
    """Frames are dictionaries containing the original capture inputs.

    All frames execute in one command list. The three history arrays (reference, aux and
    the 4x4-block low-pass ring) remain on GPU;
    Store always reads the original Refine output, and Base reads Resolve.
    The returned index map names every intermediate for independent references.
    """
    h, w = frames[0]['depth'].shape
    size = (w, h)
    lp_size = ((w+3)//4, (h+3)//4)
    job = t.create_chain(directory)
    keep = lambda name: readback is True or (isinstance(readback, (tuple,list,set)) and name in readback)
    job.raw('tiles', size=16+((w+7)//8)*((h+7)//8)*8, writable=True, readback=keep('tiles'))
    job.raw('arguments', np.array([0, 1, 1], np.uint32), writable=True, readback=keep('arguments'))
    if temporal:
        if initial_history is None:
            initial_history = [np.zeros((6,h,w,4),np.float16),np.zeros((6,h,w,2),np.uint32),
                               np.zeros((6,*lp_size[::-1],2),np.float16)]
        for name, data, fmt, extent in zip(('history_reference','history_aux','history_lp'),initial_history,
                                           (10,17,34),(size,size,lp_size)):
            job.texture(name,data,format=fmt,size=extent,layers=6,writable=True,readback=keep(name))
    head, count = initial_head, initial_count
    names = []
    for index, frame in enumerate(frames):
        if frame['depth'].shape != (h,w):
            raise ValueError('a single chain requires equal frame extents')
        prefix = f'f{index:02d}_'
        n = lambda value: prefix + value
        this = {key:n(key) for key in ('spec','diff','qs','qd','skip','normal','depth','motion',
                                      'composition','seed','seed_statistics','reference','statistics',
                                      'temporal','lp','diagnostics','base','mean',
                                      'fixed_base','fixed_mean','fixed_composition')}
        names.append(this)
        for key, value, fmt in (
                ('spec',frame['U'],10),('diff',frame['V'],10),
                ('qs',frame['qs8'],28),('qd',frame['qd8'],28),
                ('skip',frame['skip'],10),('normal',frame['packed'],24),
                ('depth',frame['depth'],41),('motion',frame['motion'],10)):
            job.texture(n(key),value,format=fmt,size=size)
        rr = frame['rr']
        job.texture(n('composition'),rgba(rr) if rr.shape[-1]==3 else rr,
                    format=10,size=size,writable=True,readback=keep('composition'))
        intermediates = ('reference','statistics','base','mean') if cached_reference else (
                         'seed','seed_statistics','reference','statistics','base','mean')
        for key in intermediates:
            data = frame['original_reference'] if key=='reference' and cached_reference else None
            job.texture(n(key),data,format=10,size=size,writable=True,readback=keep(key))
        if fixed_baseline:
            for key in ('fixed_base','fixed_mean','fixed_composition'):
                data=(rgba(rr) if rr.shape[-1]==3 else rr) if key=='fixed_composition' else None
                job.texture(n(key),data,format=10,size=size,writable=True,readback=keep(key))
        if temporal:
            for key in ('temporal','lp','diagnostics'):
                job.texture(n(key),format=10 if key=='temporal' else 34,
                            size=lp_size if key=='lp' else size,writable=True,readback=keep(key))
        flat_values = dict(DstTexSize=[w,h,1/w,1/h], Modulation=[1,1], Strength=frame.get('strength',1),
                           Anchor=frame.get('anchor',4), Mix=frame.get('mix',0), NoiseScale=2,
                           Epsilon=1e-4,Radius=3,Flags=frame.get('flags',0),
                           VerticalMode=frame.get('vertical_mode',0), VerticalStrength=frame.get('vertical_strength',0.0))
        flat_cb = t.constants('FSRDFlatDetailSeed',flat_values)
        common = [n('spec'),n('diff'),n('qs'),n('qd'),n('skip'),n('normal'),n('depth'),
                  -1,-1,'tiles',-1,-1,-1,-1]
        shader = lambda name: Path(shaders[name])
        job.reset(prefix+'ResetTiles',['tiles'],16)
        job.reset(prefix+'ResetArguments',['arguments'])
        job.compute(prefix+'Classify',shader('FSRDFlatDetailClassify'),
                    t.constants('FSRDFlatDetailClassify',dict(DstTexSize=[w,h,1/w,1/h])),
                    [n('normal'),n('skip')],['tiles','arguments'],groups=((w+7)//8,(h+7)//8,1))
        if not cached_reference:
            job.compute(prefix+'Seed',shader('FSRDFlatDetailSeed'),flat_cb,common,
                        [n('seed'),n('seed_statistics'),-1],indirect='arguments')
            common[7:9]=[n('seed'),n('seed_statistics')]
            job.compute(prefix+'Refine',shader('FSRDFlatDetailRefine'),flat_cb,common,
                        [n('reference'),n('statistics'),-1],indirect='arguments')
        common[7:9]=[n('reference'),n('statistics')]
        if fixed_baseline:
            fixed_reads=common.copy();fixed_reads[13]=n('fixed_composition')
            job.compute(prefix+'FixedBase',shader('FSRDFlatDetailBase'),flat_cb,fixed_reads,
                        [n('fixed_base'),n('fixed_mean'),-1],indirect='arguments')
            fixed_reads[10:12]=[n('fixed_base'),n('fixed_mean')];fixed_reads[13]=-1
            job.compute(prefix+'FixedApply',shader('FSRDFlatDetailApply'),flat_cb,fixed_reads,
                        [n('fixed_composition'),-1,-1],indirect='arguments')
        if temporal:
            if frame.get('reset',False):
                count=0;head=0
            p = parameters or {}
            values = dict(DstTexSize=[w,h,1/w,1/h],FullRenderSize=frame.get('full',[w,h]),
                          JitterDelta=frame.get('jitter_delta',[0,0]),Modulation=[1,1],
                          TemporalStrength=p.get('strength',1),Epsilon=1e-4,HistoryCount=count,
                          HistoryHead=head,HistoryLength=p.get('history_length',6),Flags=frame.get('flags',0),
                          CenterSigma=p.get('center_sigma',0),MotionStart=p.get('motion_start',.5),
                          MotionEnd=p.get('motion_end',2),HistoryDecay=p.get('history_decay',6))
            cb = t.constants('FSRDFlatTemporal',values)
            job.compute(prefix+'TemporalLP',shader('FSRDFlatTemporalLP'),cb,
                        [n('composition'),n('normal'),n('depth'),n('spec'),n('diff'),n('qs'),n('qd'),n('skip')],
                        [n('lp')],groups=((lp_size[0]+7)//8,(lp_size[1]+7)//8,1))
            reads = [n('reference'),n('normal'),n('depth'),n('motion'),n('skip'),'tiles',n('lp'),
                     'history_reference','history_aux','history_lp']
            job.compute(prefix+'Temporal',shader('FSRDFlatTemporal'),cb,reads,
                        [n('temporal'),n('diagnostics')],indirect='arguments')
            job.compute(prefix+'TemporalStore',shader('FSRDFlatTemporalStore'),cb,
                        [n('reference'),n('normal'),n('depth'),n('motion'),n('skip'),n('lp')],
                        ['history_reference','history_aux','history_lp'],
                        groups=((w+7)//8,(h+7)//8,1))
            common[7]=n('temporal')
            head=(head+1)%6;count=min(count+1,6)
        common[13]=n('composition')
        # Base reads the temporal residual from the reference alpha only when Resolve ran (host contract).
        base_cb = t.constants('FSRDFlatDetailSeed',dict(flat_values,TemporalDenoise=
            (parameters or {}).get('temporal_denoise',1.0) if temporal else 0.0))
        job.compute(prefix+'Base',shader('FSRDFlatDetailBase'),base_cb,common,
                    [n('base'),n('mean'),-1],indirect='arguments')
        common[10:12]=[n('base'),n('mean')]
        common[13]=-1 # Apply owns composition as UAV and never aliases it as SRV.
        job.compute(prefix+'Apply',shader('FSRDFlatDetailApply'),flat_cb,common,
                    [n('composition'),-1,-1],indirect='arguments')
    return job,names
