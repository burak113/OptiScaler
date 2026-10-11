"""Execute the actual retired-key deletions against the repository's SimpleIni.

This checks migration/deletion semantics, not the injected DLL's save UI.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', str(ROOT/'tools_tmp/floor_rewrite/gpu_tests'))).parent/'ini_tests'
# Recovery v2 keys and the modulation strengths that stay user settings.
KEPT = ['RecoveryHistory', 'RecoveryHistoryStrength', 'RecoverySpecular', 'RecoverySpecularStrength', 'RecoveryDiffuse',
        'RecoveryDiffuseStrength', 'RecoveryAnchor', 'RecoveryMix', 'RecoveryFlatAlbedo', 'RecoveryFlatAlbedoStrength',
        'RecoveryFlatAnchor', 'RecoveryFlatMix', 'RecoveryFlatRoughness', 'RecoveryDebug', 'SpecularAlbedoDemodulation',
        'DiffuseAlbedoModulation']
# Read once more only to migrate into RecoveryHistory.
MIGRATED = {'MagnifiedHistoryReset', 'MagnifiedHistoryStreakFilter', 'GeometricDisocclusionCheck'}

def run():
    text = (ROOT/'OptiScaler/Config.cpp').read_text(encoding='utf-8')
    statements = re.findall(
        r'ini.Delete\("FSR-RR", "(?:Floor\w+|RoughnessFloor|CorrelationBias|ZeroRoughHandover|FixedRoughness\w*|NormalizeAlbedoSum|BalanceSpecularRadiance|ModulationIsolation|RouteBypassedFloor|BypassAlbedoModulation|AdaptiveSpecularDemodulation|ExperimentBleedModelSource|ExperimentBleedWitnessWithoutFloor)", true\);',
        text)
    keys = [re.findall(r'"([^"]+)"',s)[1] for s in statements]
    assert len(set(keys)) == 30, keys
    assert {'ExperimentBleedModelSource', 'ExperimentBleedWitnessWithoutFloor'} <= set(keys)
    # Recovery v1 (Floor, detail recovery, bleed fix, additive split, volume restores, separate history fixes) and
    # Recovery v2's Albedo recovery (Specular and Diffuse now cover the fine bands).
    v1 = re.search(r'// Recovery v2 replaced Recovery v1.*?(for \(const char\* key : \{(.*?)\}\)\s*ini.Delete\("FSR-RR", key, true\);)',
                   text, re.S)
    assert v1, 'Recovery v1 retirement loop missing'
    v1_keys = re.findall(r'"([^"]+)"', v1.group(2))
    assert len(set(v1_keys)) == 27 and set(keys).isdisjoint(v1_keys), v1_keys
    statements.append(v1.group(1))
    keys += v1_keys
    for key in keys:
        if key not in MIGRATED:
            assert not re.search(r'read(?:Float|Int|Bool)\("FSR-RR", "'+key+r'"',text),key
        assert f'ini.SetValue("FSR-RR", "{key}"' not in text, key
    assert {'FloorEnabled', 'FloorRecovery', 'AlbedoBleedFix', 'AdditiveLightSplit', 'VolumeRestore', 'RecoveryV2',
            'RecoveryVolumetry', 'RecoveryAlbedo', 'RecoveryAlbedoStrength'} <= set(v1_keys)
    assert 'FloorRRRouting' in keys
    for key in KEPT:
        assert key not in keys, key
        assert re.search(r'read(?:Float|Int|Bool)\("FSR-RR", "'+key+r'"',text),key
        assert f'ini.SetValue("FSR-RR", "{key}"' in text,key
    OUT.mkdir(parents=True,exist_ok=True)
    fixture='[FSR-RR]\n'+''.join(k+'=123\n' for k in keys)
    fixture+='RecoveryHistory=true\nRecoverySpecularStrength=0.7\nSpecularAlbedoDemodulation=0.5\n'
    fixture+='RoughnessFloor=0.15\nDemodDivisorFloor=0.008\nUnrelated=keep\n[Other]\nFloorHandover=keep\n'
    cpp=OUT/'ini_cleanup.cpp'
    cpp.write_text('#define SI_NO_CONVERSION\n#include "'+str(ROOT/'external/simpleini/SimpleIni.h').replace('\\','/')+'"\n'
        '#include <cassert>\n#include <initializer_list>\n#include <string>\nint main(){CSimpleIniA ini;\n'
        'const char* fixture=R"fixture('+fixture+')fixture";\nassert(ini.LoadData(fixture)>=0);\n'+
        '\n'.join(statements)+'\n'+
        '\n'.join('assert(ini.GetValue("FSR-RR","'+k+'",nullptr)==nullptr);' for k in keys)+
        '\nassert(std::string(ini.GetValue("FSR-RR","Unrelated",""))=="keep");\n'
        'assert(std::string(ini.GetValue("Other","FloorHandover",""))=="keep");\n'
        'assert(std::string(ini.GetValue("FSR-RR","DemodDivisorFloor",""))=="0.008");\n'
        'std::string saved;assert(ini.Save(saved)>=0);CSimpleIniA reload;assert(reload.LoadData(saved)>=0);\n'
        'assert(std::string(reload.GetValue("FSR-RR","Unrelated",""))=="keep");\n'
        'assert(reload.GetValue("FSR-RR","FloorEnabled",nullptr)==nullptr);\n'
        'assert(reload.GetValue("FSR-RR","VolumeRestore",nullptr)==nullptr);\n'
        'assert(reload.GetValue("FSR-RR","FloorVirtualAlbedo",nullptr)==nullptr);\n'
        'assert(std::string(reload.GetValue("FSR-RR","RecoveryHistory",""))=="true");\n'
        'assert(std::string(reload.GetValue("FSR-RR","RecoverySpecularStrength",""))=="0.7");\n'
        'assert(std::string(reload.GetValue("FSR-RR","SpecularAlbedoDemodulation",""))=="0.5");}\n')
    exe=OUT/'ini_cleanup.exe'
    compile_cpp(cpp, exe)
    subprocess.run([str(exe)],check=True)
    print(f'PASS: {len(keys)} retired keys removed (Recovery v1 included); Recovery v2, modulation and unrelated INI values survive save/reload')

if __name__=='__main__':run()
