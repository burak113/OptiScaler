"""Independent CPU/source contracts for current-raw checkerboard reconstruction.
No GPU/provider/quality claim; known modes0/1/2 are the entire supported scope.
"""
from pathlib import Path
import itertools,json,math,struct
import numpy as np
ROOT=Path(__file__).resolve().parents[4]
SHADERS=ROOT/'OptiScaler/shaders/fsrd_preprocess'
CHECKS=0

def need(value,name):
    global CHECKS
    CHECKS+=1
    if not value:raise AssertionError(name)

def state(width,height,origin,rect,modes,source_sizes):
    status=int(any(m>2 or m<0 for m in modes))
    status|=2 if rect!=(width,height) or not width or not height else 0
    if any(o<0 or o>0x7fffffff-(d-1) for o,d in zip(origin,(width,height))):return status|4
    lx,ly=origin[0]+width-1,origin[1]+height-1
    for mode,(sw,sh) in zip(modes,source_sizes):status|=8 if (lx>>(mode!=2))>=sw or ly>=sh else 0
    status|=16 if width<2 and any(m!=2 for m in modes) else 0
    return status

def source_xy(x,y,origin,mode):return ((x+origin[0])>>(mode!=2),y+origin[1])
def traced(x,y,phase,mode):return mode==2 or ((x^y^phase)&1)==mode

def clean_half4(values,encoding):
    f=np.asarray(values,dtype=np.float32);y,co,cg=f[:3]
    with np.errstate(invalid='ignore'):
        rgb=np.array([y-cg+co,y+cg,y-cg-co],np.float32) if encoding else f[:3]
    rgb=np.where(np.isfinite(rgb),np.minimum(np.maximum(rgb,0),65504),0)
    rgb=np.where(rgb==0,np.float32(0),rgb).astype('<f2')
    return np.concatenate((rgb,np.array([f[3] if np.isfinite(f[3]) else 0],'<f2')))

def oct_normal(uv):
    xy=2*(np.asarray(uv,np.float64)-.5);v=np.array([*xy,1-abs(xy[0])-abs(xy[1])]);t=max(-v[2],0)
    v[:2]+=np.where(v[:2]>=0,-t,t);return v/np.linalg.norm(v)

def weight(p,q,normals,depth):
    a,b=oct_normal(normals[p[1],p[0]]),oct_normal(normals[q[1],q[0]])
    alignment=max(0,min(float(a@b),1));az,bz=abs(depth[p[1],p[0]]),abs(depth[q[1],q[0]])
    return alignment**2/(1+abs(az-bz)/max(az,bz,1e-6))

def reconstruct(source,width,height,origin,mode,phase,encoding,normals,depth):
    out=np.empty((height,width,4),'<f2');active=np.empty((height,width),bool)
    def at(x,y):
        sx,sy=source_xy(x,y,origin,mode);return clean_half4(source[sy,sx],encoding)
    for y in range(height):
        for x in range(width):
            active[y,x]=traced(x,y,phase,mode)
            if active[y,x]:out[y,x]=at(x,y);continue
            taps=[(q,y) for q in [x-1,x+1] if 0<=q<width]
            need(all(traced(*q,phase,mode) for q in taps),'only proven traced neighboring inputs used')
            if len(taps)==1:out[y,x]=at(*taps[0]);continue
            a,b=taps;wa,wb=weight((x,y),a,normals,depth),weight((x,y),b,normals,depth)
            if wa+wb>0:out[y,x]=((at(*a).astype('f4')*wa+at(*b).astype('f4')*wb)/(wa+wb)).astype('<f2')
            else:out[y,x]=at(*(a if abs(depth[a[1],a[0]]-depth[y,x])<=abs(depth[b[1],b[0]]-depth[y,x]) else b))
    return out,active

def source_contracts():
    capture=(SHADERS/'precompile/FSRDNrdRawPrePassCapture.hlsl').read_text();decode=(SHADERS/'precompile/FSRDNrdRawPrePassDecode.hlsl').read_text()
    cpp=(SHADERS/'FSRDNrdRawSignals_Dx12.cpp').read_text();header=(SHADERS/'FSRDNrdRawSignals_Dx12.h').read_text()
    need('NativeGeometry[29].zw!=RenderSize' in capture,'UINT rect compared to real logical extent')
    need('asfloat(NativeGeometry[29]' not in capture,'rect is never guessed float')
    need('NativeGeometry[36].xy' in capture and 'asint(NativeGeometry[28].zw)' in capture,'actual native selector and signed origin operands')
    for offset in ['28u*16u+8u','29u*16u+8u','32u*16u+4u','36u*16u']:need(offset in capture,'minimal live CB operands captured '+offset)
    need('GetDimensions(sw,sh)' in capture and 'GetDimensions(dw,dh)' in capture,'both actual descriptor extents bound safety')
    need('Interlocked' not in capture and 'PrivateRaw.Store(0u,status)' in capture,'one uniform status publication no cross-group clear race')
    need(capture.index('if(status!=0u)')<capture.index('NativeRawSpec.Load'),'unsupported input never sampled')
    need('logical.x>>(modes.y==2u?0u:1u)' in capture and 'logical.x>>(modes.x==2u?0u:1u)' in capture,'per-lobe packed addressing')
    need('clamp(' not in capture and 'PackNativeHalf4' in capture,'raw color not sanitized before executed codec')
    need('mode==2u||parity==mode)return SignalAt' in decode,'all traced and fullres values use exact plain decoder')
    need('(p.x^p.y^phase)&1u' in decode,'local native parity excludes origin')
    need('if(PrivateRaw.Load(0u)!=0u)' in decode,'invalid GPU header has explicit safe finite output')
    need('OutSpec[tid.xy]=0.0f;OutDiff[tid.xy]=0.0f;return;' in decode,'unsupported cannot expose uninitialized light')
    need('alignment*alignment/(1.0f+abs(az-bz)' in decode,'weights use current owned geometry only')
    # D02/WP08 experiment profile: eligibility gate + explicit unsupported policy,
    # compiled as a separate artifact; the production default above stays intact.
    need('#ifdef FSRD_NRD_SURFACE_VALID_FILL' in decode,'gated fill is a compile-time experiment profile of the same source')
    need('(InValidity[center]|InValidity[candidate])&3u' in decode,'gated candidates clear the D04 validity class before any weighting')
    need('if(wl+wr<=0.0f)return float4(0.0f,0.0f,0.0f,0.0f)' in decode,'no eligible candidate is an explicit finite-zero unsupported footprint')
    need('GateWeight(p,right)>0.0f?SignalAt(right,lobe,encoding):float4(0.0f,0.0f,0.0f,0.0f)' in decode,'single-tap edges clear the same gate')
    cpp_needles=['FSRDNrdRawPrePassValidDecode_cso','RawGuideMatches(output.validity,*context,DXGI_FORMAT_R8_UINT)','PrepareSurfaceValid']
    for needle in cpp_needles:need(needle in cpp,'gated decode profile is a distinct fail-closed host artifact: '+needle)
    need('NumDescriptors=5' in cpp,'prepass decode view heap reserves the optional validity slot')
    config=(ROOT/'OptiScaler/Config.h').read_text()
    need('FfxDenoiserNrdBridgeSurfaceValidFill {false}' in config,'experiment stays behind an OFF-by-default config key')
    for prohibited in ['history','oracle','variance']:
        need(prohibited not in decode.replace('// temporal history, or denoised native output participates in these weights.','').replace('// Dimensionless geometry only. No noisy color, oracle, variance estimate,',''),'no '+prohibited+' input/gating')
    need('views.NumDescriptors=5' in cpp and 'context->PreparePrePassSlot(*record->slot)' in cpp,'B descriptor allocation prepared during capture')
    need(cpp.index('context->PreparePrePassSlot(*record->slot)')<cpp.index('RetainComputeDispatch'),'fallible B allocation precedes native omission point')
    need('result.hasStatus=record->profile==NativeRawProfile::PrePass' in cpp and 'statusByteOffset = 0' in header,'owned status surfaced explicitly')
    need('DXGI_FORMAT_R10G10B10A2_UNORM' in cpp and 'DXGI_FORMAT_R32_FLOAT' in cpp,'owned decode geometry formats checked')
    ledger=(ROOT/'OptiScaler/misc/RecordedComputeLease_Dx12.h').read_text()
    need('std::function<void(const SubmissionInfo&)> completed;' in ledger and '!completed' in ledger,'append-only completion callback participates in Empty')
    need('for (const auto& submission : detached)' in ledger and 'callback.callbacks.completed(callback.info)' in ledger,'only actual detached submissions trigger completion callback')
    need('FailUntrackedRequiredSubmission(E_FAIL)' in ledger,'completion callback exception has sticky required failure')
    need('const auto totalBytes=rawBytes+flagBytes+statusBytes' in cpp and 'permit.SetBytes(totalBytes)' in cpp,'mandatory readback actual allocation counted in same family limit')
    need('CopyBufferRegion(record->slot->statusReadback.Get(),0,record->slot->resource.Get(),0,4)' in cpp,'only four owned status bytes copied without title access')
    need('std::array<uint64_t,RecordedComputeLease::PollBudget> active' in cpp,'submission observation storage bounded and allocation-free')
    need('Remove(info.submissionId);failed=true' in cpp and 'if(!failed&&!pending)' in cpp,'only own failed ID removed and final successful completion may map')
    need('callbacks.completed=[observation]' in cpp,'status observation always registered independent of Trace')
    for name in ['FSRDNrdRawSignals_Dx12.cpp','FSRDNrdRawSignals_Dx12.h','precompile/FSRDNrdRawPrePassCapture.hlsl','precompile/FSRDNrdRawPrePassCaptureRoot.hlsl','precompile/FSRDNrdRawPrePassDecode.hlsl']:
        b=(SHADERS/name).read_bytes();need(b'\n' not in b.replace(b'\r\n',b''),'CRLF '+name)

def numeric_contracts():
    rng=np.random.default_rng(0x15CB2026);width,height=9,6;normals=np.full((height,width,2),.5);depth=np.ones((height,width),'f4')*5
    source=np.empty((height+3,width+6,4),'<f2');source[...,:3]=rng.uniform(-.5,2,source[...,:3].shape);source[...,3]=rng.uniform(-1,12,source[...,3].shape)
    preserved=0;reconstructed=0
    for origin,mode,phase,encoding in itertools.product([(0,0),(1,2),(3,3)],[0,1,2],[0,1],[0,1]):
        need(state(width,height,origin,(width,height),(mode,mode),(source.shape[1::-1],)*2)==0,'supported native shape admitted')
        output,active=reconstruct(source,width,height,origin,mode,phase,encoding,normals,depth)
        for y,x in np.argwhere(active):
            sx,sy=source_xy(int(x),int(y),origin,mode);expected=clean_half4(source[sy,sx],encoding)
            need(np.array_equal(output[y,x].view('<u2'),expected.view('<u2')),'every traced RGBA exact through plain decoder');preserved+=1
        need(np.isfinite(output).all(),'entire reconstructed RR input finite');reconstructed+=int((~active).sum())
        if mode==2:need(active.all(),'mode2 has no reconstructed pixel')
    for mode,phase in itertools.product([0,1],[0,1]):
        constant=np.full_like(source,[.25,.5,.75,-0.]);output,active=reconstruct(constant,width,height,(1,2),mode,phase,0,normals,depth)
        need(np.all(output[...,:3]==constant[0,0,:3]),'constant radiance and DC preserved including borders')
        need(np.array_equal(output[active,3].view('<u2'),np.full(active.sum(),0x8000,'<u2')),'traced native signed alpha zero remains exact')
    sizes=((128,128),(128,128))
    for modes in [(0,0),(0,1),(1,0),(1,1),(2,2),(0,2),(2,1)]:need(state(128,128,(0,0),(128,128),modes,sizes)==0,'known mode combinations supported')
    need(state(128,128,(0,0),(128,128),(3,2),sizes)&1,'unknown selector explicit status')
    need(state(128,128,(0,0),(struct.unpack('<I',struct.pack('<f',128))[0],128),(2,2),sizes)&2,'float-encoded dimensions not reinterpreted as UINT')
    for origin in [(-1,0),(0,-1),(0x7fffffff,0),(0,0x7fffffff)]:need(state(128,128,origin,(128,128),(2,2),sizes)&4,'negative and signed-overflow origins rejected before load')
    need(state(128,128,(1,0),(128,128),(2,2),sizes)&8,'fullres source extent checked')
    need(state(128,128,(0,0),(128,128),(0,1),((63,128),(128,128)))&8,'packed actual source width checked')
    need(state(1,1,(0,0),(1,1),(0,1),((1,1),(1,1)))&16,'unreconstructable one-pixel checkerboard explicit status')
    need(state(1,1,(0,0),(1,1),(2,2),((1,1),(1,1)))==0,'one-pixel fullres remains supported')
    # A pure depth discontinuity reduces the distant tap without examining lighting.
    p=(4,2);left=(3,2);right=(5,2);depth[2,5]=100
    need(weight(p,left,normals,depth)>weight(p,right,normals,depth)>0,'geometry-only cross-edge weight suppression')
    edge=np.empty_like(source);edge[:]=[1,0,0,7];edge[:,5:]=[0,0,1,9]
    out,active=reconstruct(edge,width,height,(0,0),1,0,0,normals,depth)
    need(not active[2,4] and out[2,4,0]>out[2,4,2],'untraced cross-edge reconstruction prefers matching depth')
    return {'traced_exact_rgba_checks':preserved,'untraced_reconstructed_pixels':reconstructed}

def main():
    source_contracts();counts=numeric_contracts();print('PASS raw_prepass_cpu_checks='+str(CHECKS));print(json.dumps({'checks':CHECKS,**counts,'scope':'independent CPU/source mechanics; no native/GPU/provider/game activation/quality proof','gpu_run':False,'compiler_run':False}))
if __name__=='__main__':main()
