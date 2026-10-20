"""Portable CPU colour research, extracted without mathematical changes.

B4 is the audited CPU baseline. C8/soft2 is a REJECTED quality candidate.
This is not an AMD RR replay or the final game remodulated composite.
The bilinear function is the original ideal CPU sampler, not a GPU sampler.
"""
import sys
import numpy as np

c = sys.modules[__name__]
L = np.array([.2126, .7152, .0722], np.float32)


def octdec(o):
    u=2*(o-.5)
    n=np.concatenate([u,(1-np.abs(u).sum(-1))[...,None]],-1)
    t=np.maximum(-n[...,2],0)
    n[...,:2]+=np.where(n[...,:2]>=0,-t[...,None],t[...,None])
    return n/np.maximum(np.linalg.norm(n,axis=-1,keepdims=True),1e-12)


def pack_old(o):
    q=np.floor(np.clip(o*.5+.5,0,1)*255+.5)
    return (q[...,0]*256+q[...,1])/65535


def unpack_old(p):
    q=np.floor(p*65535+.5); x=np.floor(q/256)
    return np.stack([x,q-x*256],-1)/255*2-1


def pack_new(o):
    q=np.floor(np.clip(o,0,1)*np.array([63,31],np.float32)+.5)
    return q[...,0]*32+q[...,1]


def unpack_new(p):
    x=np.floor(p/32)
    return np.stack([x,p-x*32],-1)/np.array([63,31],np.float32)


def lum(v):return np.sum(v[...,:3]*L,-1,dtype=np.float32)


def half_rtz(v):
    a=np.asarray(v,np.float32)
    h=a.astype(np.float16)
    return np.where(np.abs(h.astype(np.float32))>np.abs(a),np.nextafter(h,np.float16(0)),h).astype(np.float32)


def bilinear(v,x,y):
    H,W=v.shape[:2]
    xi=np.floor(x).astype(np.int32);yi=np.floor(y).astype(np.int32)
    fx=(x-xi).astype(np.float32);fy=(y-yi).astype(np.float32)
    r=np.zeros(x.shape+v.shape[2:],np.float32)
    for dx,dy,w in [(0,0,(1-fx)*(1-fy)),(1,0,fx*(1-fy)),(0,1,(1-fx)*fy),(1,1,fx*fy)]:
        vv=v[np.clip(yi+dy,0,H-1),np.clip(xi+dx,0,W-1)]
        r+=vv*w[...,None] if v.ndim==3 else vv*w
    return r


def apply(y,g,x=None,dark=False,quant=True):
    H,W=y.shape[:2];qH,qW=g.shape[:2]
    fy,fx=np.mgrid[:H,:W].astype(np.float32)
    gu=bilinear(g,(fx+.5)*qW/W-.5,(fy+.5)*qH/H-.5)
    if dark:gu=1+(gu-1)*np.clip(lum(x)/.0003,0,1)[...,None]
    yy=half_rtz(y) if quant else y
    out=yy*gu;out*= (lum(yy)/np.maximum(lum(out),1e-9))[...,None]
    if quant:out=half_rtz(np.clip(out,0,65500))
    return out


def rshare(v,mask):
    s=np.moveaxis(gaussian(np.moveaxis(v,-1,0),6),0,-1)
    return float(np.median((s[...,0]/np.maximum(s.sum(-1),1e-9))[mask]))


def gaussian(a, s):
    """Separable Gaussian over the last two axes with edge clamping."""
    r = int(3 * s + 0.5)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / s) ** 2)
    k /= k.sum()

    def conv(x, ax):
        pad = [(0, 0)] * x.ndim
        pad[ax] = (r, r)
        p = np.pad(x, pad, mode='edge')
        if r > 24:  # large sigma: same edge-clamped result via FFT (sigma <= 8 keeps the exact direct path)
            n = p.shape[ax] + 2 * r
            f = np.fft.irfft(np.fft.rfft(p.astype(np.float64), n, axis=ax)
                             * np.expand_dims(np.fft.rfft(k, n), [d for d in range(x.ndim) if d != ax]), n, axis=ax)
            sl = [slice(None)] * x.ndim
            sl[ax] = slice(2 * r, 2 * r + x.shape[ax])
            return f[tuple(sl)].astype(np.float32)
        out = np.zeros_like(x, dtype=np.float32)
        for i, w in enumerate(k):
            sl = [slice(None)] * x.ndim
            sl[ax] = slice(i, i + x.shape[ax])
            out += w * p[tuple(sl)]
        return out

    return conv(conv(a.astype(np.float32), a.ndim - 2), a.ndim - 1)


def box(v,cell):
    H,W=v.shape[:2];qh,qw=H//cell,W//cell
    return v[:qh*cell,:qw*cell].reshape((qh,cell,qw,cell)+v.shape[2:]).mean(axis=(1,3),dtype=np.float32)


def spatial(y,x,z,n,step,colour_edge=0):
    H,W=z.shape;ys=np.zeros_like(y);xs=np.zeros_like(x);ws=np.zeros_like(z)
    cy=y/np.maximum(c.lum(y),1e-6)[...,None]
    for dy in range(-2,3):
        for dx in range(-2,3):
            yy=np.clip(np.arange(H)[:,None]+dy*step,0,H-1);xx=np.clip(np.arange(W)[None,:]+dx*step,0,W-1)
            tz=z[yy,xx];dz=np.clip(1-abs(z-tz)/np.maximum(.02*abs(z),.001),0,1)
            dn=np.clip((np.sum(n*n[yy,xx],-1)-.9)*10,0,1)
            w=np.float32(np.exp(-.5*(dx*dx+dy*dy)))*dz*dz*dn*dn
            w*=np.isfinite(z)&np.isfinite(tz)&(z*tz>0)
            if colour_edge:w*=np.exp(-np.sum((cy-cy[yy,xx])**2,-1)/(2*colour_edge**2))
            ys+=w[...,None]*y[yy,xx];xs+=w[...,None]*x[yy,xx];ws+=w
    return ys/np.maximum(ws,1e-6)[...,None],xs/np.maximum(ws,1e-6)[...,None]


def rawgain(target,colour):
    tc=target/np.maximum(c.lum(target),1e-9)[...,None]
    cc=colour/np.maximum(c.lum(colour),1e-9)[...,None]
    g=tc/np.maximum(cc,1e-6);g/=np.maximum(c.lum(cc*g),1e-9)[...,None]
    return np.clip(g,.75,1.33)


class Model:
    def __init__(self,name,**cfg):
        self.name=name;self.cfg=cfg;self.cell=cfg.get('cell',4);self.hist=None
    def frame(self,x,y,z,n,m):
        q=self.cell;H,W=x.shape[:2];qh,qw=H//q,W//q
        x,y=c.half_rtz(x),c.half_rtz(y)
        if self.cfg.get('winsor'):
            bx=box(x,q);threshold=np.repeat(np.repeat(c.lum(bx),q,0),q,1)
            xx=x[:qh*q,:qw*q];ratio=np.minimum(1,self.cfg['winsor']*threshold/np.maximum(c.lum(xx),1e-9))
            xs=box(xx*ratio[...,None],q)
        else:xs=box(x,q)
        ys=box(y,q);zs=box(z,q);ms=box(m,q)
        ns=c.octdec(c.unpack_new(c.half_rtz(c.pack_new(box(n,q)))))
        ys,xs,zs,ms=map(c.half_rtz,(ys,xs,zs,ms))
        colour,source=spatial(ys,xs,zs,ns,self.cfg.get('step',2),self.cfg.get('colour_edge',0))
        representation=self.cfg.get('representation','rgb')
        if representation=='chroma':source/=np.maximum(c.lum(source),1e-9)[...,None]
        elif representation=='loggain':source=np.log(rawgain(source,colour))
        yy,xx=np.mgrid[:qh,:qw].astype(np.float32)
        target=source
        if self.hist is not None:
            px=xx+ms[...,0]/q;py=yy+ms[...,1]/q
            hist=c.bilinear(self.hist,px,py)
            expected=zs+ms[...,2]
            valid=((px+.5)/qw>=0)&((px+.5)/qw<=1)&((py+.5)/qh>=0)&((py+.5)/qh<=1)&(abs(hist[...,3])>1e-9)
            valid&=abs(hist[...,3]-expected)<=.02*np.maximum(abs(expected),.001)
            a=self.cfg.get('alpha',.25)
            target=np.where(valid[...,None],(1-a)*hist[...,:3]+a*source,source)
        self.hist=c.half_rtz(np.concatenate([target,zs[...,None]],-1))
        g=np.exp(target) if representation=='loggain' else rawgain(target,colour)
        g=c.half_rtz(g)
        out=c.apply(y,g)
        return out,dict(g=g,z=zs,n=ns,colour=ys)


def jbu(y,z,n,d,colour_edge=.2,gradient=False,fallback='identity',confidence_scale=0):
    g=d['g'];qh,qw=g.shape[:2];H,W=y.shape[:2]
    yy,xx=np.mgrid[:H,:W].astype(np.float32);px=(xx+.5)*qw/W-.5;py=(yy+.5)*qh/H-.5
    xi=np.floor(px).astype(np.int32);yi=np.floor(py).astype(np.int32);fx=px-xi;fy=py-yi
    gn=np.zeros_like(y);ws=np.zeros_like(z)
    nr=c.octdec(n);cy=y/np.maximum(c.lum(y),1e-6)[...,None]
    qc=d['colour']/np.maximum(c.lum(d['colour']),1e-6)[...,None]
    if gradient:
        zl=np.concatenate([z[:,:1],z[:,:-1]],1);zr=np.concatenate([z[:,1:],z[:,-1:]],1)
        zu=np.concatenate([z[:1],z[:-1]],0);zd=np.concatenate([z[1:],z[-1:]],0)
        gx=np.where(abs(z-zl)<abs(zr-z),z-zl,zr-z)
        gy=np.where(abs(z-zu)<abs(zd-z),z-zu,zd-z)
    for dx,dy,wb in [(0,0,(1-fx)*(1-fy)),(1,0,fx*(1-fy)),(0,1,(1-fx)*fy),(1,1,fx*fy)]:
        iy=np.clip(yi+dy,0,qh-1);ix=np.clip(xi+dx,0,qw-1)
        tz=d['z'][iy,ix]
        pred=z
        if gradient:
            offx=(ix+.5)*W/qw-.5-xx;offy=(iy+.5)*H/qh-.5-yy
            pred=z+np.clip(gx*offx+gy*offy,-.25*abs(z),.25*abs(z))
        dz=np.clip(1-abs(pred-tz)/np.maximum(.02*abs(z),.001),0,1)
        dn=np.clip((np.sum(nr*d['n'][iy,ix],-1)-.9)*10,0,1)
        w=wb*dz*dz*dn*dn
        if colour_edge:w*=np.exp(-np.sum((cy-qc[iy,ix])**2,-1)/(2*colour_edge**2))
        gn+=w[...,None]*g[iy,ix];ws+=w
    if fallback=='bilinear':
        base=c.bilinear(g,px,py)
        corrected=np.where((ws>1e-6)[...,None],gn/np.maximum(ws,1e-6)[...,None],base)
        confidence=np.clip(ws*confidence_scale,0,1) if confidence_scale else np.ones_like(ws)
        gn=base+(corrected-base)*confidence[...,None]
    else:
        gn=np.where((ws>1e-6)[...,None],gn/np.maximum(ws,1e-6)[...,None],1)
    yy=c.half_rtz(y);out=yy*gn;out*=(c.lum(yy)/np.maximum(c.lum(out),1e-9))[...,None]
    return c.half_rtz(out)


def metric(stack,mask,den):
    a=np.stack(stack)
    cc=a-c.lum(a)[...,None]
    hp=np.empty_like(cc)
    for i,v in enumerate(cc):
        sm=np.moveaxis(c.gaussian(np.moveaxis(v,-1,0),2),0,-1)
        hp[i]=v-sm
    std=np.sqrt(np.sum(np.var(hp,axis=0),axis=-1))/den
    flat=std[mask]
    lc=c.lum(a);lcv=lc.std(0)/np.maximum(lc.mean(0),1e-6)
    return {'chroma_HF_temporal_p50':float(np.median(flat)),
            'chroma_HF_temporal_p90':float(np.percentile(flat,90)),
            'chroma_HF_temporal_mean':float(flat.mean()),
            'luma_fineCV_p50':float(np.median(lcv[mask]))}



CFG = {"B4": {"cell": 4, "step": 2},
       "C8_edge": {"cell": 8, "step": 1, "colour_edge": .2}}

def baseline_model():
    """Fresh B4 state. Feed chronological frames without replay loops."""
    return Model("B4", **CFG["B4"])

def rejected_soft2_model():
    """Fresh C8 target state; this candidate failed shifted-edge safety."""
    return Model("C8_edge", **CFG["C8_edge"])

def rejected_soft2_apply(y, z, n, data):
    """Original soft2 JBU: sigma .4, gradient, bilinear fallback, scale 2."""
    return jbu(y, z, n, data, .4, True, "bilinear", 2)
