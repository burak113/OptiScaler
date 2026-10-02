"""SOURCE only. Runtime calls require a fresh root stage authority."""
from pathlib import Path
import hashlib, json, os, struct, sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
RUNTIME=HERE/'runtime_once'
W,H,N=128,80,64
HALF_BYTES=W*H*8
ORDER=('A1','B1','B2','A2')
MEASURES=('TOTAL',)
IN_FMT=(10,41,10,10,41,41,10,10,41,10,10,10,10,10,41,41,10)
OUT_FMT=(10,10,10,24,28,28,10,10)
NATIVE_FMT=(41,10,24,28,28,10,10)
COMP_FMT=(10,28,10,28,10,24,10,41,10,10,3)
SPECCODES=((48,56,64,72,80,72,64,56),
           (56,60,64,68,72,68,64,60),
           (40,52,64,76,88,76,64,52))
DIFFCODES=(80,48,64)
LIGHTDIV=(64,96,80)
LIGHTCODES=(0,1,2,3,4,3,2,1,0,-1,-2,-3,-4,-3,-2,-1)

def load(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def record(p):
    p=Path(p).resolve()
    with p.open('rb') as f:
        h=hashlib.sha256()
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return dict(path=str(p),bytes=p.stat().st_size,sha256=h.hexdigest())
def check(r):
    assert record(r['path'])==r, 'identity changed: '+r['path']
def save(p,v):
    with Path(p).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(v,f,indent=2,allow_nan=False); f.write('\n')
def write(p,b):
    with Path(p).open('xb') as f: f.write(b)
    return record(p)
def quote(p):
    s=Path(p).resolve().as_posix()
    assert '"' not in s and '\\' not in s
    return '"'+s+'"'
def tokens(s):
    """Inverse of C++ std::quoted delimiter='"', escape='\\'; no raw regex."""
    out=[];i=0
    while i<len(s):
        if s[i].isspace(): i+=1;continue
        if s[i]=='"':
            i+=1;v=''
            while i<len(s) and s[i]!='"':
                if s[i]=='\\': i+=1;assert i<len(s)
                v+=s[i];i+=1
            assert i<len(s);i+=1;out.append(v)
        else:
            j=i
            while i<len(s) and not s[i].isspace(): i+=1
            out.append(s[j:i])
    return out
def gpujob(d,cso,cb,srvs,uavs):
    assert len(srvs) in (11,17) and len(uavs) in (3,8)
    lines=[f'{quote(cso)} {quote(cb)} {W} {H} {len(srvs)} {len(uavs)} 1']
    lines += [f'{quote(p)} {W} {H} {fmt}' for p,fmt in srvs+uavs]
    text='\n'.join(lines)+'\n';t=tokens(text)
    assert t[:7]==[str(Path(cso).resolve().as_posix()),str(Path(cb).resolve().as_posix()),str(W),str(H),str(len(srvs)),str(len(uavs)),'1']
    for i,(p,fmt) in enumerate(srvs+uavs):
        assert t[7+4*i:11+4*i]==[Path(p).resolve().as_posix(),str(W),str(H),str(fmt)]
    write(d/'job.txt',text.encode()); return str(d/'job.txt')
def nativejob(d,inputs,provider,outs):
    text=f'{W} {H} {N} 2 32 0 1 0 {quote(provider)}\n'
    text+=''.join(f'{quote(r["path"])} {fmt} {frames}\n' for r,fmt,frames in inputs)
    text+=' '.join(quote(p) for p in outs)+'\n';t=tokens(text)
    assert len(t)==32 and t[:8]==['128','80','64','2','32','0','1','0']
    assert t[8]==Path(provider).resolve().as_posix()
    for i,(r,fmt,frames) in enumerate(inputs):
        assert t[9+3*i:12+3*i]==[Path(r['path']).resolve().as_posix(),str(fmt),str(frames)]
    assert t[30:]==[Path(p).resolve().as_posix() for p in outs]
    write(d/'job.txt',text.encode());return str(d/'job.txt')
def assets(): return load(HERE/'ASSETS.json')
def item(name): return assets()['named'][name]
def source_check():
    freeze=load(HERE/'source_freeze.json')
    for r in freeze['records']+assets()['records']: check(r)
    return record(HERE/'source_freeze.json')
def valid_rgb(np,a,label,known_alpha=True):
    assert np.isfinite(a if known_alpha else a[...,:3]).all(), label+': nonfinite consumed words'
    assert (a[...,:3]>=0).all() and (a[...,:3]<65504).all(), label+': negative or saturated RGB'
def result(stage): return RUNTIME/stage/'result.json'
PREREQS={'assemble':(), 'produce':('assemble',), 'native':('produce',),
         'endpoint':('native',), 'score_endpoint':('endpoint',),
         'remaining':('score_endpoint',), 'score_all':('remaining',)}
def authorize(stage,path):
    if sys.flags.optimize or not __debug__: raise RuntimeError('optimized assertions prohibited')
    a=load(path);assert a['root_authorized_once'] is True and a['stage']==stage
    assert a['source_freeze']==source_check()
    check(a['peer_PASS']);peer=load(a['peer_PASS']['path']);assert a['peer_status'] in str(peer)
    check(a['python_EXE']);assert Path(sys.executable).resolve()==Path(a['python_EXE']['path']).resolve()
    expected=[str(result(s).resolve()) for s in PREREQS[stage]]
    assert [r['path'] for r in a['prerequisites']]==expected
    for r in a['prerequisites']:
        check(r);v=load(r['path']);assert v['stage_PASS'] is True and v['all_children_CLOSED'] is True
        for pin in v['outputs']+v['prerequisite_pins']: check(pin)
    return a
