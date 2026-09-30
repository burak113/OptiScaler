"""Local read-only hit-distance contract extraction; no native/GPU calls."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
sources={
 'header':('external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h',[413,433,434]),
 'docs':('external/FidelityFX-SDK-v2/Kits/FidelityFX/docs/techniques/denoising.md',[546,552,806]),
 'sample':('external/FidelityFX-SDK-v2/samples/Denoisers/FidelityFX_Denoiser/dx12/shaders/trace_rays_denoiser.hlsl',[227,229,250,269,299,300,323,324]),
 'converter':('OptiScaler/shaders/fsrd_preprocess/precompile/FSRDInputConv.hlsl',[923,926,934,935,967,974,977,1158,1159]),
 'common':('OptiScaler/shaders/fsrd_preprocess/precompile/FSRDPreprocessCommon.hlsli',[213,215])}
out=dict(schema='local-indirect-specular-hit-distance-contract-review-v1',new_GPU_or_native_calls=0,sources={},findings=[
 'Header specifies indirect-specular input alpha as ray hit distance and output as preserved. It gives no strict-positive requirement or zero-is-miss assertion.',
 'Packaged docs say hit distance must be valid for active signal, otherwise negative; they do not explicitly exclude zero. Validity at zero cannot be certified from this wording.',
 'SDK sample initializes untraced/miss distance65504 and writes65504 for primary sky; geometric secondary hits use actual ray-origin-to-hit distance. Zero is not its miss/sky sentinel.',
 'Local converter accepts finite input distance in[0,65504]; missing indirect input falls back to max(abs(viewSpacePos.z),.001). It then multiplies indirect-specular distance by custom roughness tracking SoftBelow(.30,.15).',
 'At roughness.55 tracking is0, so finite input/fallback yields alpha0 as measured. This local virtual-hit handover is not a documented SDK default or positivity violation proof.',
 'Direct-signal undefined nonnegative alpha and dominant-visibility[0,FP16_MAX] semantics must not be substituted for indirect-specular hit semantics.',
 'Uniform alpha0 is an observable diagnostic input. Changing it to positive changes operator virtual geometry; no provider/history cause or game quality fix follows.'])
for key,(relative,lines) in sources.items():
 p=ROOT/relative;text=p.read_text().splitlines();out['sources'][key]=dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),lines={str(i):text[i-1] for i in lines})
out['analysis_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
p=HERE/'specular_hit_contract_review.json';assert not p.exists();p.write_text(json.dumps(out,indent=2)+'\n');print(hashlib.sha256(p.read_bytes()).hexdigest())
