"""Exact NEW13-pass graph layout for source tests and granted GPU research.

Import/constant/layout preparation is CPU only. compile_shaders and executing
the returned ChainJob require the lead's serialized compiler/GPU slot. This
owns no title COM reference and cannot install or invoke a game hook.
"""
from pathlib import Path
import struct
import numpy as np

from fsrd_gpu_chain import FORMATS,compile_shader


PRE = Path(__file__).resolve().parents[2]/'fsrd_preprocess/precompile'
HISTORY,COARSEST,FINAL = 1,2,4


def constants(width,height,level_size,level,flags,frame,jitter=(0,0),jitter_delta_uv=(0,0),strength=(1,1,4,.25)):
    if width<=0 or height<=0 or len(level_size)!=4 or min(level_size)<=0 or not 0<=level<=6:
        raise ValueError('positive full/level extents and bounded pyramid index required')
    floats = [width,height,1/width,1/height,*level_size,*strength,*jitter,*jitter_delta_uv,
              .03,3,8,8,.02,.95,.025,.75,6,1/16,0,0]
    if len(floats)!=28 or not np.isfinite(floats).all():
        raise ValueError('exact finite sevenfloat4 rows required')
    data = struct.pack('<28f4I',*floats,flags,level,frame,0)
    if len(data)!=128:
        raise AssertionError('new graph constants must match eight16-byte HLSL rows')
    return data


def compile_shaders(directory):
    directory = Path(directory)
    return {role:compile_shader(PRE/('FSRDNrdLobeRecovery'+role+'.hlsl'),directory/(role+'.cso'))
            for role in ('Reference','Down','Band')}


def zero_texture(job,name,size,format=2,readback=False):
    """Use the actual runner's documented '-' zero upload, no giant zero files.

    Native default+upload resources remain real. This saves scratch bytes; it
    does not claim zero GPU/CPU allocation or bypass native initialization.
    """
    if name in job.names:
        raise ValueError('duplicate graph resource '+name)
    width,height = size
    dtype,channels = FORMATS[format]
    shape = (height,width)+((channels,) if channels>1 else ())
    index = len(job.resources)
    job.names[name] = index
    job.resources.append(dict(name=name,kind=2,width=width,height=height,layers=1,format=format,
        writable=True,input=Path('-'),output=(job.directory/('out_%03d_%s.bin'%(index,name)) if readback else None),shape=shape))
    return name


class LobeGraph:
    def __init__(self,job,shaders,width,height,prefix='recovery',readback_history=False):
        self.job,self.shaders,self.width,self.height,self.prefix = job,shaders,width,height,prefix
        self.sizes = [(width,height)]
        for _ in range(6):
            w,h = self.sizes[-1]
            self.sizes.append(((w+1)//2,(h+1)//2))
        self.history = []
        for ping in range(2):
            group = {name:zero_texture(job,'%s_hist%d_%s'%(prefix,ping,name),(width,height),
                format=3 if name=='geometry' else 2,readback=readback_history)
                for name in ('spec','diff','geometry','gradient')}
            group['noise'] = [zero_texture(job,'%s_hist%d_noise%d'%(prefix,ping,level),self.sizes[level],readback=readback_history)
                              for level in range(6)]
            self.history.append(group)
        self.levels = [{name:zero_texture(job,'%s_level%d_%s'%(prefix,level,name),size)
                        for name in ('spec','diff','metadata')} for level,size in enumerate(self.sizes)]
        self.corrections = [{name:zero_texture(job,'%s_correction%d_%s'%(prefix,level,name),self.sizes[level])
                             for name in ('spec','diff')} for level in range(6)]

    def record(self,index,inputs,jitter=(0,0),jitter_delta_uv=(0,0),history_valid=None,readback=True,
               output_prefix=None,strength=(1,1,4,.25)):
        if set(inputs)!=set(('spec','diff','rr_spec','rr_diff','depth','normals','motion')):
            raise ValueError('exact seven noisy/RR/guide inputs required')
        job = self.job
        previous,self_next = self.history[1-(index&1)],self.history[index&1]
        level0 = self.levels[0]
        prefix = output_prefix or '%s_frame%03d'%(self.prefix,index)
        output = {signal:zero_texture(job,prefix+'_'+signal,(self.width,self.height),format=10,readback=readback)
                  for signal in ('spec','diff')}
        flag = HISTORY if (index>0 if history_valid is None else history_valid) else 0
        def cb(level,size,flags=flag):
            return constants(self.width,self.height,size,level,flags,index,jitter,jitter_delta_uv,strength)
        groups = lambda size:((size[0]+7)//8,(size[1]+7)//8,1)
        job.compute(prefix+'_reference',self.shaders['Reference']['output'],cb(0,(*self.sizes[0],*self.sizes[1])),
            [inputs[name] for name in ('spec','diff','rr_spec','rr_diff','depth','normals','motion')]+
            [previous[name] for name in ('spec','diff','geometry','gradient')],
            [self_next[name] for name in ('spec','diff','geometry','gradient')]+[level0[name] for name in ('spec','diff','metadata')],groups(self.sizes[0]))
        for level in range(1,7):
            fine,coarse = self.levels[level-1],self.levels[level]
            job.compute(prefix+'_down%d'%level,self.shaders['Down']['output'],cb(level,(*self.sizes[level],*self.sizes[level-1])),
                [fine[name] for name in ('spec','diff','metadata')],[coarse[name] for name in ('spec','diff','metadata')],groups(self.sizes[level]))
        for level in reversed(range(6)):
            fine,coarse = self.levels[level],self.levels[level+1]
            extra = (COARSEST if level==5 else 0)|(FINAL if level==0 else 0)
            coarse_correction = [-1,-1] if level==5 else [self.corrections[level+1][s] for s in ('spec','diff')]
            srvs = [fine[s] for s in ('spec','diff','metadata')]+[coarse[s] for s in ('spec','diff','metadata')]+coarse_correction
            srvs += [previous['noise'][level]]+[inputs[s] for s in ('motion','depth','normals','rr_spec','rr_diff','spec','diff')]
            srvs += [previous['geometry'],level0['metadata']]
            uavs = [self.corrections[level][s] for s in ('spec','diff')]+[self_next['noise'][level]]+[output[s] for s in ('spec','diff')]
            if len(srvs)!=18 or len(uavs)!=5:
                raise AssertionError('band layout must match the actual shader root signature')
            job.compute(prefix+'_band%d'%level,self.shaders['Band']['output'],
                cb(level,(*self.sizes[level],*self.sizes[level+1]),flag|extra),srvs,uavs,groups(self.sizes[level]))
        return output

    def allocated_native_bytes(self):
        # Packed resource payload only. Real upload row padding/native driver
        # allocations are measured separately by the actual process, not guessed.
        return sum(int(np.prod(r['shape']))*FORMATS[r['format']][0].itemsize for r in self.job.resources)
