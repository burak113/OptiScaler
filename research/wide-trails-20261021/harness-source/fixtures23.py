"""Named task-23 lighting fixtures, additive to Step and Freeze."""
from .fixtures import Step, Freeze
from .fixtures import _Wrapped
from .captures import Capture
import numpy as np

STEP_PRESETS23={
    'dim':dict(at=48,gain=.5,box=None),
    'bright':dict(at=48,gain=2.,box=None),
    'local':dict(at=48,gain=3.,box=(0,300,128,550)),
}

def fixture(name, capture='d6d2a083'):
    if name=='freeze': return Freeze(capture,40,128,step_at=48,gain=.5)
    return Step(capture,**STEP_PRESETS23[name])

class LocalPulse23(_Wrapped):
    """Real, unlooped noise frames with a screen-local light toggling every period frames."""
    def __init__(self,src='d6d2a083',at=48,period=16,gain=2.,box=(0,300,128,550)):
        src=src if isinstance(src,Capture) else Capture(src)
        super().__init__(src,f'pulse23v1_at{at}_period{period}_gain{gain:g}_box'+('_'.join(map(str,box)) if box else 'all'))
        self.at,self.period,self.gain,self.box=at,period,gain,box
    def gain_at(self,i):return self.gain if i>=self.at and ((i-self.at)//self.period)%2==0 else 1.
    def gain_map(self,i):
        g=np.ones((self.H,self.W,1),np.float32);v=self.gain_at(i)
        if self.box:
            x0,y0,x1,y1=self.box;g[y0:y1,x0:x1]=v
        else:g[:]=v
        return g
    def raw(self,i,name):
        b=self.src.raw(i,name)
        if self.gain_at(i)==1 or name not in ('input_diffuse','input_specular'):return b
        x=np.frombuffer(b,np.float16).reshape(self.H,self.W,4).astype(np.float32)
        x[...,:3]*=self.gain_map(i);return np.minimum(x,65504).astype(np.float16).tobytes()
    def rgb(self,i,kind='in'):
        x=self.src.rgb(i,kind);return x*self.gain_map(i) if kind=='in' else x
