"""Signal plan policy and its Config/menu wiring.

The C++ part checks every routing request against the documented rules, the legacy INI
migration and the runtime status packing. The source checks pin how Config reads, migrates
and saves the keys, so a retired key can neither come back nor be dropped unmigrated.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]
RETIRED = ['SignalCount', 'Signal1', 'Signal2', 'Signal3', 'Signal4', 'DiffuseSignalType', 'SpecularSignalType',
           'ApproximateSpecHitDistance', 'ApproximateRayHitDistance', 'UnsupportedAlbedoRecovery']
KEYS = ['DiffuseSignal', 'SpecularSignal', 'EstimateHitDistances', 'DenoiseDiffuse', 'DenoiseSpecular',
        'AlbedoBleedFix', 'AlbedoBleedFixDiffuse']


def check_sources():
    config = (ROOT/'OptiScaler/Config.cpp').read_text(encoding='utf-8-sig')
    for key in KEYS:
        assert f'ini.SetValue("FSR-RR", "{key}"' in config, key
    for key in RETIRED:
        assert f'ini.SetValue("FSR-RR", "{key}"' not in config, key
        assert f'"{key}"' in config[config.index('// Migrated to the keys above'):], key
    assert 'readRoute("DiffuseSignal")' in config and 'readRoute("SpecularSignal")' in config
    assert 'FSRDSignals::FromLegacy(' in config
    # The legacy fix key is only a fallback for the new one.
    assert config.index('readBool("FSR-RR", "AlbedoBleedFix")') < config.index(
        'readBool("FSR-RR", "UnsupportedAlbedoRecovery")')
    # Profiles own Floor/recovery only.
    profile = config[config.index('void Config::ApplyFfxDenoiserProfile'):config.index('bool Config::ResetFfxDenoiserSettings')]
    assert not re.search(r'UnsupportedAlbedo|Route|DenoiseDiffuse|DenoiseSpecular|EstimateHitDistances', profile)
    reset = config[config.index('bool Config::ResetFfxDenoiserSettings'):]
    reset = reset[:reset.index('\n}\n') if '\n}\n' in reset else reset.index('\r\n}\r\n')]
    for field in ['FfxDenoiserDiffuseRoute', 'FfxDenoiserSpecularRoute', 'FfxDenoiserEstimateHitDistances',
                  'FfxDenoiserDenoiseDiffuse', 'FfxDenoiserDenoiseSpecular', 'FfxDenoiserUnsupportedAlbedoRecovery',
                  'FfxDenoiserAlbedoBleedFixDiffuse']:
        assert field + '.reset()' in reset, field

    feature = (ROOT/'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp').read_text(encoding='utf-8-sig')
    # One plan source for context creation and the per-frame check.
    assert feature.count('FSRDSignals::MakePlan(') == 2
    assert 'FfxDenoiserSignalCount' not in feature and 'Approximate' not in feature.replace(
        'FSRDConvFlags::Approximate', '')
    # The per-frame guide check uses the policy's contract, which knows the diffuse copy's
    # slot has a view-depth ray length; conversion must then supply that length.
    resolve = feature[feature.index('RRResult FSRDFeatureDx12::ResolveSignalTypes('):]
    resolve = resolve[:resolve.index('\nRRResult FSRDFeatureDx12::')]
    assert 'FSRDSignals::Feedable(_plan,' in resolve and 'available' not in resolve
    assert re.search(r'if \(estimateHitDistances \|\| _plan\.diffuseCopy\)\s*_convDesc\.Flags \|= '
                     r'uint32_t\(FSRDConvFlags::ApproximateRayHitDistance\)', feature)
    # Only the diffuse copy replaces the diffuse lobe's second slot; specular-only keeps routing.
    assert re.search(r'GetIndirectDiffuseSignal\(_indirectDiffuseSignal,\s*_unsupportedAlbedoRecovery && '
                     r'_plan\.diffuseCopy\);', feature)
    assert 'ConfigureSignalResources(_extraDiffuseSignal, _extraSpecularSignal, _plan.albedoFix,' in feature

    menu = (ROOT/'OptiScaler/menu/menu_common.cpp').read_text(encoding='utf-8-sig')
    upscalers = menu.index('void MenuCommon::RenderActiveUpscalerSettings(')
    body = menu[upscalers:menu.index('\nvoid MenuCommon::', upscalers + 1)]
    # The denoiser section follows the upscaler selection, and FSR-RR's settings live inside it.
    assert body.index('SeparatorText("Upscalers")') < body.index('RenderDenoiserSettings(ctx);')
    assert 'FSR-RR Advanced Settings' not in body
    denoiser = menu.index('void MenuCommon::RenderDenoiserSettings(')
    denoiser = menu[denoiser:menu.index('\nvoid MenuCommon::', denoiser + 1)]
    gate = denoiser.index('if (choice.fsrRR)')
    for item in ['DrawProfile(', 'DrawAlbedoFix(', 'DrawSignalSummary(', 'FSR-RR Advanced Settings', 'DrawRouting(']:
        assert denoiser.index(item) > gate, item
    # The fix sits with the modulation strengths it depends on.
    assert (denoiser.index('CollapsingHeader("Conversion & Modulation")') < denoiser.index('DrawAlbedoFix(')
            < denoiser.index('CollapsingHeader("Floor")'))
    print('PASS: Config migrates/saves routing keys; FSR-RR settings sit inside the denoiser section')


def run():
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT/'tools_tmp/fsrd_menu_20261004/tests'))/'signal_policy'
    exe = out/'fsrd_signal_policy_test.exe'
    compile_cpp(Path(__file__).with_name('fsrd_signal_policy_test.cpp'), exe)
    subprocess.run([str(exe)], check=True)
    check_sources()


if __name__ == '__main__':
    run()
