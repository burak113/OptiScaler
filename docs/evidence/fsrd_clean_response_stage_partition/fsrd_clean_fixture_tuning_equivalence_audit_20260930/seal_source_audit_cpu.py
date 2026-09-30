"""Compact exact source-contract audit. No SDK/native/helper/build/scorer call."""
from pathlib import Path
import hashlib,json,re,struct,subprocess
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent
def rec(p,lines=None):
 p=Path(p).resolve();b=p.read_bytes();r=dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
 if lines is not None:r['lines']=lines
 return r
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
last=subprocess.check_output(['git','log','-2','--format=%H'],cwd=ROOT,text=True).splitlines()
assert head=='50e376ce8c99739efbd9a86055dbe4995d50155e'
assert last==[head,'3b5b0b4b14f7fdab20e9297a388f2c4cfec88712']
sdk=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h'
mirror=ROOT/'OptiScaler/include/fsr-rr/ffx_denoiser.h'
cfg=ROOT/'OptiScaler/Config.h';feature=ROOT/'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'
runner=ROOT/'tools_tmp/fsrd_weak_material_clean_native_preparation_20260930/frozen_runner/source_reference.cpp'
sdktext=sdk.read_text();mirror_text=mirror.read_text();cfgtext=cfg.read_text();ftext=feature.read_text();rtext=runner.read_text()
rows=[
 (6,'DISOCCLUSION_THRESHOLD',.1,'FfxDenoiserDisocThreshold','0.1f','DisocclusionThreshold',541,542,3913,'Depth-comparison disocclusion threshold during temporal reprojection.'),
 (1,'CROSS_BILATERAL_NORMAL_STRENGTH',.5,'FfxDenoiserCrossBlNormStr','0.5f','CrossBilateralNormalStrength',526,543,3916,'Strength of the cross bilateral normal term.'),
 (2,'STABILITY_BIAS',.5,'FfxDenoiserStabilityBias','0.5f','TemporalStabilityBias',529,544,3919,'Temporal accumulation bias toward greater stability and lower responsiveness.'),
 (3,'MAX_RADIANCE',40000.,'FfxDenoiserMaxRadiance','4e4f','MaxRadiance',532,545,3922,'Maximum radiance value; not a documented multiplicative gain.'),
 (4,'RADIANCE_CLIP_STD_K',40.,'FfxDenoiserRadianceClip','40.0f','RadianceClipDeviation',535,546,3925,'Standard-deviation K used for radiance clipping; not a documented gain.'),
 (5,'GAUSSIAN_KERNEL_RELAXATION',.5,'FfxDenoiserGaussKernRelax','0.5f','GaussianKernelRelaxation',538,547,3928,'Gaussian kernel relaxation factor; not a documented sharpness scalar.')]
mapping=[]
for key,name,value,member,literal,ini,hline,cline,pline,meaning in rows:
 symbol='FFX_API_CONFIGURE_DENOISER_KEY_'+name
 assert re.search(re.escape(symbol)+r'\s*=\s*'+str(key)+r'\s*,',sdktext)
 assert re.search(re.escape(symbol)+r'\s*=\s*'+str(key)+r'\s*,',mirror_text)
 assert re.search(re.escape(member)+r'\s*\{\s*'+re.escape(literal)+r'\s*\}',cfgtext)
 assert symbol in rtext and symbol in ftext
 mapping.append(dict(key=key,symbol=symbol,fixture_value=value,production_fork_default=value,exact_same_float32_literal_value=True,config_member=member,INI_section='FSR-RR',INI_key=ini,public_semantics=meaning,public_header_line=hline,Config_h_line=cline,production_update_line=pline))
assert 'const float values[]={.1f,.5f,.5f,40000.f,40.f,.5f};'in rtext
assert 'ff(api.Configure(&context,&c.header),"configuration")'in rtext
assert 'GET_DEFAULT_KEYVALUE'not in rtext
assert rtext.count('api.Query(')==1 and '&version.header' in rtext
assert 'FfxDenoiserUseAmdDefaults { false }'in cfgtext
assert 'requestedValue = useAmdDefaults ? amdDefault : cfgValue.value_or_default()'in ftext
assert 'if (requestedValue == currentValue)'in ftext and 'currentValue = previousValue;'in ftext
roundtrip=ROOT/'tools_tmp/fsrd_weak_material_clean_roundtrip_preparation_20260930'
rr=json.loads((roundtrip/'registration.json').read_text());cb=(roundtrip/'payloads/cb.bin').read_bytes()
assert len(cb)==96 and struct.unpack_from('<f',cb,20)[0]==0 and struct.unpack_from('<I',cb,52)[0]==0 and struct.unpack_from('<I',cb,64)[0]==0
logs=[ROOT/'tools_tmp/fsrd_weak_material_clean_native_preparation_20260930/planned_native'/c/'stdout.log'for c in('C0','C1')]
for p in logs:
 text=p.read_text();assert 'dispatches=64'in text and 'configure baseline'not in text
 assert len(text.splitlines())==4
sources=[rec(sdk,[111,114,121,124,127,459,462,469,472,475,524,526,527,529,530,532,533,535,536,538,539,541,542,544]),rec(mirror,[90,93,94,95,218,219,220,221,222,223]),
 rec(cfg,[24,27,96,99,311,312,313,316,514,515,516,518,524,525,527,528,537,540,542,543,544,545,546,547]),
 rec(ROOT/'OptiScaler/Config.cpp',[385,386,387,388,389,390,391,404,420,421]),
 rec(feature,[1541,1552,1555,1558,1559,1560,1561,1562,1563,1564,1942,1949,1950,1951,3482,3486,3493,3494,3507,3889,3895,3896,3902,3907,3913,3916,3919,3922,3925,3928,4152,4169,4175,4178,4179,4180,4183,4187,4193,4196,4197,4198,4201]),
 rec(ROOT/'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.h',[35,36,39,43,44,45,46,47,48,62,67,71]),
 rec(runner,[106,111,113,115,116,117,118]),
 rec(ROOT/'OptiScaler/upscalers/fsr31/FSR31Feature_Dx12.cpp',[94,96,544,547,550,552,553,560,561]),
 rec(ROOT/'OptiScaler/upscalers/IFeature.cpp',[248,250,253,255,257,264]),
 rec(ROOT/'OptiScaler/upscalers/IFeature_Dx12.cpp',[55,58,69,71,140,161,190]),
 rec(roundtrip/'registration.json'),rec(roundtrip/'payloads/cb.bin')]+[rec(p)for p in logs]
save('source_pins.json',dict(records=sources,HEAD=head,previous_commit=last[1],few_targeted_sources=True,no_expanded_mass_tables=True))
save('audit.json',dict(status='PASSED_BOUNDED_SOURCE_TUNING_EQUIVALENCE_AUDIT',HEAD=head,previous_commit=last[1],
 main_result='All six cleanB342 explicit scalar overrides exactly match this fork production defaults under UseAmdDefaults=false and unset INI/menu overrides. They are not known numeric AMD provider defaults.',
 fixture_key_order=[6,1,2,3,4,5],fixture_value_order=[.1,.5,.5,40000.,40.,.5],mapping=mapping,
 configuration_call_contract=dict(public_api='ffxConfigureDescDenoiserKeyValue: non-null denoiser context, enum key, count1, pointer to onefloat for keys1..6.',fixture='tuning=1 sends all6 Configure calls once after context creation before frame loop. Failure checked by ff().',production='Context creation queries all7 default keys, caches provider baseline, then per-frame configuration chooses provider defaults or fork cfg values. Calls Configure only when requested scalar differs; failed configure rolls current-value cache back for retry.',production_call='FSRDFeatureDx12::ApplyConfiguration constructs count1/key/data and calls FfxApiProxy::D3D12_Configure.',parameter_naming='No singular SetParameter() occurs in inspected OptiScaler/public-denoiser C++ source. FSR31FeatureDx12::SetParameters is a separate NGX helper setting OptiScaler.SupportsUpscaleSize; no six-key SDK mapping there.',equivalence_limit='Same key IDs/types/numericfloat values, not identical query/configure call sequence or proof of whole production-path equivalence. No private side-effect inference.'),
 default_scalar_observation=dict(AMD_numeric_defaults_available_in_public_header=False,AMD_numeric_defaults_observed_in_this_audit=False,
 existing_pinned_fixture_logs=[rec(p)for p in logs],fixture_source_default_query=False,fixture_source_only_query='Provider-version query; default-key query absent.',production_supported_query='ffxQueryDescDenoiserGetDefaultKeyValue count1, keys1..7; cached at context creation.',production_log_format='[RR_DIAG] configure baseline (AMD default -> fork default), active source={}; six AMD->cfg scalar values. FSRDFeature1555-1564.',scope_limit='No production baseline-query log was supplied or observed in these bounded known artifacts. Existing semantic/allocator-feasibility audits contained no matching numeric default proof. No game logs, other chats, old trace forest, SDK query or native call searched/executed.'),
 separate_runtime_controls=dict(native_sdk_gain_sharpen_detail_key='None among the public keys1..7; keys1..6 have the semantics above, key7 is debug linear-depth bounds.',
 production_floor='FloorEnabled=true/FloorRecovery1 default; recovery becomes FloorDetailPreservation and composition constants. Separate luma/chroma recovery1 and demodulation/modulation1 controls exist. These are OptiScaler converter/composition controls, not SDK six-key gain.',
 fixture_floor='Clean roundtrip/composition CB has DetailPreservation0,HistoryValid0,WriteHistory0. Hence recovery/history path bypassed; native B342 runner has no OptiScaler composition/SR/RCAS stage.',
 production_sharpen='OverrideSharpness=false/RcasEnabled=false defaults; actual sharpness comes from NGX default0 when absent. Override value0.4 is effective only when enabled. FSR31 built-in sharpening uses the selected value unless externalRCAS enabled; outerRCAS uses its separate constants.',
 fixture_sharpen='Standalone native+outputcomp helper has no FSR31 upscale/sharpness/outerRCAS; no sharpen parameter is sent by the6-key fixture.',
 bias_conclusion='No documented runtime gain/detail/sharpness parameter is established here as a correction for current weak-patch gain/DC departure. These other controls show full-pipeline scope differences only; no tuning recommendation, calibration, grid or causal effect asserted.'),
 interpretation='Synthetic departure under this frozen cohort and explicit fork-default native tuning is not by itself proof of a production or AMD-default defect. Full composition/SR settings, resources and public-provider-default numeric baseline remain separately qualified.',
 reviewer_search_failures_preserved='Targeted rg attempts using path wildcard suffixes failed on Windows error123; corrected searches used -g filters/exact paths. They produced no source findings or mutations.',
 actual_new_GPU_native_build_scores_models=0,no_game_run=True,no_setting_or_source_changes=True,quality_accepted=False,source_pins=rec(HERE/'source_pins.json')))
for r in sources:
 now=rec(r['path']);assert all(now[k]==r[k]for k in('path','bytes','sha256'))
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==head
files=[rec(p)for p in sorted(HERE.rglob('*'))if p.is_file()and p.name!='completion_manifest.json']
save('completion_manifest.json',dict(status='SEALED_CPU_SOURCE_AUDIT',files=files,self_entry_excluded=True,source_pins=rec(HERE/'source_pins.json'),HEAD=head,no_new_GPU_native_build_scores=True))
for n in('audit.json','source_pins.json','completion_manifest.json'):print(json.dumps(rec(HERE/n)))
