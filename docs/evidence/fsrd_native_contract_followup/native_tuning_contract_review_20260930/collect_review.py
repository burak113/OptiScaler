"""Local contracts/default provenance only; no provider call, GPU or tracked change."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
paths={
 'header':'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h',
 'SDK_sample_documentation':'external/FidelityFX-SDK-v2/docs/samples/denoiser.md',
 'SDK_sample_implementation':'external/FidelityFX-SDK-v2/Samples/Denoisers/FidelityFX_Denoiser/dx12/denoiserrendermodule.cpp',
 'runner':'OptiScaler/shaders/shader_tools/tests/fsrd_rr_runner.cpp',
 'production_config':'OptiScaler/Config.h',
 'production_feature':'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp',
 'production_menu':'OptiScaler/menu/menu_common.cpp'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
items=[
 (6,'DISOCCLUSION_THRESHOLD',.1,'Depth comparison threshold during temporal reprojection',[.01,.05],[.01,1.0],541,'FfxDenoiserDisocThreshold'),
 (1,'CROSS_BILATERAL_NORMAL_STRENGTH',.5,'Strength of cross-bilateral normal term',[0,1],[0,1],526,'FfxDenoiserCrossBlNormStr'),
 (2,'STABILITY_BIAS',.5,'Bias of temporal accumulation toward greater stability and less responsiveness',[0,1],[.1,.9],529,'FfxDenoiserStabilityBias'),
 (3,'MAX_RADIANCE',40000,'Maximum radiance scalar',[0,65504],[10,65500],532,'FfxDenoiserMaxRadiance'),
 (4,'RADIANCE_CLIP_STD_K',40,'Standard deviation K value used for radiance clipping',[0,65504],[1,500],535,'FfxDenoiserRadianceClip'),
 (5,'GAUSSIAN_KERNEL_RELAXATION',.5,'Gaussian kernel relaxation factor',[0,1],[0,1],538,'FfxDenoiserGaussKernRelax')]
keys=[]
for key,name,value,meaning,sdk_range,fork_range,line,config in items:
 keys.append(dict(key_id=key,key='FFX_API_CONFIGURE_DENOISER_KEY_'+name,header_meaning=meaning,
  format='single float, count1',native_runner_override=value,production_fork_default=value,
  production_config_field=config,provider_default_numeric_value=None,provider_default_measured=False,
  SDK_sample_UI_range=sdk_range,production_UI_range=fork_range,documented_API_numeric_constraint=None,
  header_line=line))
result=dict(schema='native-tuning-local-contract-review-v1',analysis_sha256=sha(Path(__file__)),quality_accepted=False,
 no_GPU_calls=True,no_provider_query_executed=True,
 sources={name:dict(path=str(ROOT/p),sha256=sha(ROOT/p)) for name,p in paths.items()},keys=keys,
 important_distinctions=[
  'Native runner six literal Configure values equal current Config.h fork defaults. They are not established provider defaults.',
  'Header supplies scalar types and qualitative purposes, but no numeric legal ranges, algorithms, history lengths or exact clipping formula.',
  'SDK sample sliders/docs expose UI ranges, not API validity rules. Disocclusion.1 exceeds sampleUImax.05 but fits productionUImax1 and previous Configure calls returned OK; invalid-API claim is unsupported.',
  'RadianceClipStdK40 is a K parameter for radiance clipping; local sources do not specify the statistical estimator, support, exact cutoff equation, or interaction with stability. It is not documented as40percent/40frames.',
  'StabilityBias.5 is a bias parameter; no local API contract equates it to exactly50percent prior-frame blending or a known accumulation length. Menu prose is qualitative.',
  'Native MAX_RADIANCE40000 is far above these small synthetic signals, but effect normalization/internals are unavailable; this alone does not prove it inert.' ],
 default_query_contract=dict(available_in_local_SDK=True,header_lines=[459,462,468,471,475],
  descriptor='ffxQueryDescDenoiserGetDefaultKeyValue',type='FFX_API_QUERY_DESC_TYPE_DENOISER_GET_DEFAULT_KEYVALUE (effect sub-ID0x81)',
  required_context='non-nullptr denoiser ffxContext*',fields='header type, key uint64, count1, data pointer to float',
  SDK_sample_uses='SetDefaultConfiguration(key), sample lines805-854; it queries each key rather than baking numeric defaults.',
  production_uses='FSRDFeature_Dx12::SetDefaultConfiguration lines4144-4176; initialization captures queried values into _denoiserAmdDefaults atline1552.',
  production_AB='FfxDenoiserUseAmdDefaults defaults false in Config.h540. UpdateConfiguration lines3881-3922 chooses queried defaults vs slider/fork values and Configure applies any changed value; failure retries rather than treating it applied.',
  caveat='Existing runner asks provider-version query only; failure of that separate query does not establish default-key-query failure. Header availability is not a measured successful query for this direct effect DLL.',
  safe_numeric_record='If a separate diagnostic queries defaults, initialize each result toNaN and record return code; treat as measured only onOK with finite float. Query DEFAULT does not expose current post-Configure values.'),
 tuning_zero_diagnostic=dict(justified=True,scope='One Boolean mode control disables the bundle of all six explicit effect-key Configure calls in unchanged pinned runner.',
  preserved='Same runner bytes, provider, context flags/signals/dimensions, seven input payloads, applied184-byte dispatch controls, initial reset/jitter/camera and resource initialization.',
  changed='Only job tuning field1→0 and branch-driven six Configure calls present→absent; defaults supplied internally by same fresh provider context.',
  interpretation='Descriptive sensitivity of repeatability to fork override bundle vs untouched provider initialization. It does not isolate K40 or stability.5, identify the cause, prove provider defect, or test game quality.',
  design='Preregister four fresh pinned-binary source contexts with tuning0; retain rawFP16 diffuse/spec output hashes and arrays plus selected composition. Compare RGB/alpha, before/afterlighting32 windows and composed differences; keep originals.',
  no_threshold_sweep=True,quality_acceptance=False),
 metadata_qualification=[
  'Pin runner/provider/source/controls/driver/adapter/dimensions/signals/API version and context createflags, each fresh context log/process returncodes.',
  'Record tuning0/no effect-key Configure calls; requested six override values must be absent/null or explicitly unused, not mislabeled applied.',
  'If keys were successfully queried in a separately identified utility, pin utility source/binary/provider/context, key/returncode/floatbits and timing beforeconfiguration. Do not pretend samepinned runner emitted query logs if it did not.',
  'If queries unavailable/failed/not performed, numeric provider defaults remain unknown; report provider-initialized/nooverride behavior only. Do not fill unknowns with fork constants, sample slider endpoints, orzero initialization.',
  'Global debug Configure remains active in tuning0; the mode skips denoiser tuning keys, not every Configure call.',
  'Input/appliedcontrol equality and changed job tuning flag are complementary proofs;184byte dispatch records do not include context configuration values.',
  'Four-context pair ranges are descriptive, not a confidence interval or general stability guarantee.' ],
 cause_boundary='No local numeric contract establishes K40/stability.5 as wrong or as the source of observed variance; bundled tuning0 is a bounded diagnostic only.')
out=HERE/'review.json';assert not out.exists();out.write_text(json.dumps(result,indent=2)+'\n');print('review_sha256',sha(out))
