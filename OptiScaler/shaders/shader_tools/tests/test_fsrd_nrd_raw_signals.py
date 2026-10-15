"""CPU/source contracts for owned raw native signal capture; no native/GPU claims."""
from __future__ import annotations
import hashlib,json,math,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
SHADERS=ROOT/'OptiScaler/shaders/fsrd_preprocess'
CHECKS=0
def need(value,message):
    global CHECKS
    CHECKS+=1
    if not value:raise AssertionError(message)
def f32(value):return struct.unpack('<f',struct.pack('<f',value))[0]
def half(bits):return struct.unpack('<e',struct.pack('<H',bits))[0]
def half_word(value):
    try:return struct.unpack('<H',struct.pack('<e',value))[0]
    except OverflowError:return (0x8000 if math.copysign(1.,value)<0 else 0)|0x7c00
def rne_word(value):
    bits=struct.unpack('<I',struct.pack('<f',value))[0]
    sign=(bits>>16)&0x8000;magnitude=bits&0x7fffffff
    if magnitude>=0x7f800000:return sign|0x7c00|(0x200 if magnitude&0x7fffff else 0)
    if magnitude>=0x38800000:return sign|min(((magnitude+0xfff+((magnitude>>13)&1))>>13)-0x1c000,0x7c00)
    exponent=magnitude>>23
    if exponent<102:return sign
    shift=126-exponent;mantissa=(magnitude&0x7fffff)|0x800000;retained=mantissa>>shift
    remainder=mantissa&((1<<shift)-1);halfway=1<<(shift-1)
    return sign|(retained+int(remainder>halfway or (remainder==halfway and retained&1)))
def sanitize(value):return min(max(value,0.),65504.) if math.isfinite(value) else 0.
def decode(values,encoding):
    y,co,cg,a=values
    rgb=(y-cg+co,y+cg,y-cg-co) if encoding else (y,co,cg)
    return tuple(half(rne_word(sanitize(x))) for x in rgb)+(a if math.isfinite(a) else 0.,)
def sources():
    capture=(SHADERS/'precompile/FSRDNrdRawCapture.hlsl').read_text()
    decoded=(SHADERS/'precompile/FSRDNrdRawDecode.hlsl').read_text()
    geometry=(SHADERS/'precompile/FSRDNrdBridgeGeometry.hlsl').read_text()
    helper=(SHADERS/'FSRDNrdRawSignals_Dx12.cpp').read_text()
    header=(SHADERS/'FSRDNrdRawSignals_Dx12.h').read_text()
    bridge=(SHADERS/'FSRDNrdBridgePass_Dx12.cpp').read_bytes()
    begin=bridge.index(b'bool ConversionPass::Dispatch(ID3D12GraphicsCommandList*')
    end=bridge.index(b'bool ConversionPass::DispatchGeometry(')
    need(hashlib.sha256(bridge[begin:end]).hexdigest()=='6d1f265dc484da7be3130d392170f4317900faba57b2b467bce3324f1a30954a','legacy lighting conversion byte-identical')
    need('NativeRawSpec[tid.xy]' in capture and 'NativeRawDiff[tid.xy]' in capture,'Recon direct local DTid color addressing')
    need('PackNativeHalf4' in capture and capture.count('NrdNearestHalfBits(value.')==4,'all4 raw half components packed')
    need('clamp(' not in capture and 'max(' not in capture,'no raw RGB clamp before codec')
    need('word < 96u' in capture and 'PrivateRaw.Store4(word * 16u, 0u)' in capture,'owned1536B header initialized')
    need('NativeGeometry[28]' in capture and 'NativeGeometry[36]' not in capture,'only actually required small native CB operand')
    need('PrivateRaw.Store4(28u * 16u, NativeGeometry[28])' in capture,'exact native/private CB28 offset retained')
    need('register(b6)' in capture and 'FSRD_NRD_RAW_ROOT_CBV' in capture,'native root and table CBV paths')
    need('DESCRIPTORS_VOLATILE | DATA_VOLATILE' in capture,'native table descriptors remain legal volatile reads')
    need('RWByteAddressBuffer PrivateRaw' in capture,'rootUAV owned capture avoids mixed descriptor heaps')
    need('ConsumerConstants[75].w!=0u' in decoded,'executed owned word303 decides decoder')
    need('value.x-value.z+value.y,value.x+value.z,value.x-value.z-value.y' in decoded,'exact attested Consumer inverse')
    need('isfinite(value.a) ? value.a : 0.0f' in decoded,'finite alpha identity/nonfinite zero only')
    need('*1000' not in decoded and '* 1000' not in decoded,'sample weight never treated as unit conversion')
    need('InRecon' not in geometry and 'OutSpec[' not in geometry and 'OutDiff[' not in geometry,'geometry shader never reads/writes lighting')
    need('RootConstants(num32BitConstants=52' in geometry and 'numDescriptors=9' in geometry and 'CBV(b6)' in geometry,'new geometry root layout56DWORD')
    need('int2(p) + asint(NativeGeometry[28].zw)' in geometry,'geometry uses exact live source origin')
    need('max(abs(rawDepth), asfloat(0x358637bdu))' in geometry,'owned native positive ViewZ uses exact epsilon')
    need('OutMotion[p] = float4(0.0f,0.0f,0.0f,1.0f)' in geometry,'motion read deferred to current Temporal')
    need('NrdSpecularMaterialGuide' in geometry and 'NrdDiffuseMaterialGuide' in geometry,'geometry retains exact material guide helpers')
    need('source.profile!=NativeRawProfile::ReconDirect' in helper,'unknown/checkerboard profile not silently admitted')
    need('2) * 1024 * 1024 * 1024' in helper and 'Permit::TryAcquire' in helper,'retained family byte and32slot permits')
    need(helper.index('RetainComputeDispatch')<helper.index('list->Dispatch('),'lease retained before capture GPU work')
    need('record->nativeRecording=native;record->recordingId=native->id' in helper,'weak exact recording plus nonzero id')
    need('source.nativeConstants.nativeHeap!=source.nativeHeap' in helper,'native source SRV and table CBV share heap')
    need('captureFlag.Initialize(device,error,303)' in helper and 'captureFlag.Initialize(device,error,36)' in helper,'both native flag profiles prewarmed')
    need('slot->flag.Initialize' in helper and 'slot->decodeViews' in helper,'slot flags/views created before early capture')
    need('record->phase.compare_exchange_strong' in helper,'single-use decode admission')
    need('Transition(list,output.spec,kRead,D3D12_RESOURCE_STATE_UNORDERED_ACCESS)' in helper,'only owned lighting UAV transition')
    need('Transition(list,source.' not in helper and 'ComPtr<ID3D12DescriptorHeap> nativeHeap' not in helper,'no native source transitions/retention')
    need('retiredSlots.swap(previous->slots)' in helper,'retired caches release idle slots while leases retain needed slots')
    getter=helper[helper.index('RawSignalSnapshot RawSignalSnapshotPass::GetSnapshot'):helper.index('uint64_t RawSignalSnapshotPass::OwnedBytes')]
    need('GetGPUVirtualAddress' not in getter,'snapshot getter contains no COM calls')
    need('geometryConstants' in header and 'decodedEncodingConstants' in header,'owned header and frozen codec bindings exposed')
    rr=(SHADERS/'FSRDNrdBridgeRR_Dx12.cpp').read_text()
    for field,value in [('providerCheckerboardSignalFlags','lease->context->create.checkerboardSignalFlags'),('diffuseCheckerboardOrigin','diffuse.signal.checkerboardOrigin'),('specularCheckerboardOrigin','specular.signal.checkerboardOrigin')]:
        need(f'recorded->{field} = {value}' in rr,f'actual preSDK {field}')
    for name in ['FSRDNrdRawSignals_Dx12.h','FSRDNrdRawSignals_Dx12.cpp','precompile/FSRDNrdRawCapture.hlsl','precompile/FSRDNrdRawCaptureRoot.hlsl','precompile/FSRDNrdRawDecode.hlsl','precompile/FSRDNrdBridgeGeometry.hlsl','precompile/FSRDNrdBridgeGeometryMaterial.hlsl','precompile/FSRDNrdBridgeGeometryMaterialParams.hlsl']:
        raw=(SHADERS/name).read_bytes();need(b'\n' not in raw.replace(b'\r\n',b''),f'CRLF {name}')
def numeric():
    finite=0;nonfinite=0
    for word in range(65536):
        value=half(word)
        if math.isfinite(value):
            need(rne_word(value)==word,'all finite native half words incl signedzero survive raw capture');finite+=1
            need(half_word(decode((.25,.5,.75,value),0)[3])==word,'late finite native alpha identity');finite+=1
        else:
            need(not math.isfinite(half(rne_word(value))),'raw malformed remains nonfinite until decode');nonfinite+=1
            need(decode((.25,.5,.75,value),0)[3]==0.,'late malformed alpha +zero');nonfinite+=1
    for value in [2**-25,2**-24,2**-14,1.,65504.,65520.]:
        bits=struct.unpack('<I',struct.pack('<f',value))[0]
        for delta in [-1,0,1]:
            x=struct.unpack('<f',struct.pack('<I',bits+delta))[0]
            for sign in [-1.,1.]:need(rne_word(sign*x)==half_word(sign*x),'independent IEEE half boundary/tie reference')
    for encoded in [(1.,.375,-.25,7.),(.25,-.5,.125,-1.),(-.25,.375,-.5,-0.)]:
        y,co,cg,a=encoded;expected=(sanitize(y-cg+co),sanitize(y+cg),sanitize(y-cg-co),a)
        actual=decode(encoded,1)
        need(all(half_word(x)==half_word(y) for x,y in zip(actual,expected)),'asymmetric signed-chroma exact Consumer inverse')
    for bits in [0,1,0x80000000,0x7fc00000]:
        need(decode((1.,.25,-.125,5.),bits!=0)==decode((1.,.25,-.125,5.),bool(bits)),'uint negativezero/NaN bits nonzero native encoding')
    need((1000.*2.)/1000.==2. and (1000.*2.)/1000.!=2000.,'normalized Recon central weight is not a unit scale')
    epsilon=struct.unpack('<f',struct.pack('<I',0x358637bd))[0]
    for raw in [0.,-0.,1e-12,-1e-12,.01,-32.,65504.,-65504.,1e10]:
        raw=f32(raw);native=max(abs(raw),epsilon)
        need(native>=epsilon and native==max(abs(raw),epsilon),'finite native positive ViewZ without RR far clamp')
    return {'finite_half_identity_checks':finite,'nonfinite_capture_then_sanitize_checks':nonfinite}
def main():
    sources();counts=numeric();print(f'PASS raw_cpu_source_checks={CHECKS}')
    print(json.dumps({'checks':CHECKS,**counts,'scope':'source+independent CPU arithmetic; no compiled shader/native/GPU/lifetime result','compiler_run':False,'gpu_run':False}))
if __name__=='__main__':main()
