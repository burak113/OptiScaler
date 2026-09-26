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

def run():
    text = (ROOT/'OptiScaler/Config.cpp').read_text(encoding='utf-8')
    statements = re.findall(
        r'ini.Delete\("FSR-RR", "(?:Floor\w+|RoughnessFloor|CorrelationBias|ZeroRoughHandover|FixedRoughness\w*|NormalizeAlbedoSum|BalanceSpecularRadiance|ModulationIsolation|RouteBypassedFloor|BypassAlbedoModulation|AdaptiveSpecularDemodulation)", true\);',
        text)
    keys = [re.findall(r'"([^"]+)"',s)[1] for s in statements]
    assert len(set(keys)) == 29, keys
    for key in keys:
        if key != 'FloorDetailPreservation':  # Read-only migration to the linear master.
            assert not re.search(r'read(?:Float|Int|Bool)\("FSR-RR", "'+key+r'"',text),key
    new = {'FloorEnabled','FloorRecovery','FloorHandoverAnchorClamp','FloorHandoverCorrelationMix',
           'SpecularAlbedoDemodulation','DiffuseAlbedoModulation','FloorFlatRecovery',
           'FloorSpecularRecovery','FloorDiffuseRecovery','FloorFlatNoiseMethod',
           'FloorSpecularNoiseMethod','FloorDiffuseNoiseMethod','FloorLumaRecovery','FloorChromaRecovery'}
    assert new.isdisjoint(keys)
    assert 'FloorRRRouting' in keys
    assert 'readInt("FSR-RR", "FloorRRRouting")' not in text
    assert 'ini.SetValue("FSR-RR", "FloorRRRouting"' not in text
    for key in new:
        assert re.search(r'read(?:Float|Int|Bool)\("FSR-RR", "'+key+r'"',text),key
        assert f'ini.SetValue("FSR-RR", "{key}"' in text,key
    OUT.mkdir(parents=True,exist_ok=True)
    fixture='[FSR-RR]\n'+''.join(k+'=123\n' for k in keys)
    fixture+='FloorEnabled=false\nFloorNoiseSuppression=0.4\nFloorRecovery=0.6\n'
    fixture+='FloorHandoverAnchorClamp=2.5\nFloorHandoverCorrelationMix=0.6\n'
    fixture+='FloorRRRouting=1\n'
    fixture+='RoughnessFloor=0.15\nDemodDivisorFloor=0.008\nUnrelated=keep\n[Other]\nFloorHandover=keep\n'
    cpp=OUT/'ini_cleanup.cpp'
    cpp.write_text('#define SI_NO_CONVERSION\n#include "'+str(ROOT/'external/simpleini/SimpleIni.h').replace('\\','/')+'"\n'
        '#include <cassert>\n#include <string>\nint main(){CSimpleIniA ini;\n'
        'const char* fixture=R"fixture('+fixture+')fixture";\nassert(ini.LoadData(fixture)>=0);\n'+
        '\n'.join(statements)+'\n'+
        '\n'.join('assert(ini.GetValue("FSR-RR","'+k+'",nullptr)==nullptr);' for k in keys)+
        '\nassert(std::string(ini.GetValue("FSR-RR","Unrelated",""))=="keep");\n'
        'assert(std::string(ini.GetValue("Other","FloorHandover",""))=="keep");\n'
        'assert(std::string(ini.GetValue("FSR-RR","DemodDivisorFloor",""))=="0.008");\n'
        'assert(std::string(ini.GetValue("FSR-RR","FloorEnabled",""))=="false");\n'
        'std::string saved;assert(ini.Save(saved)>=0);CSimpleIniA reload;assert(reload.LoadData(saved)>=0);\n'
        'assert(std::string(reload.GetValue("FSR-RR","Unrelated",""))=="keep");\n'
        'assert(reload.GetValue("FSR-RR","FloorNoiseSuppression",nullptr)==nullptr);\n'
        'assert(std::string(reload.GetValue("FSR-RR","FloorRecovery",""))=="0.6");\n'
        'assert(reload.GetValue("FSR-RR","FloorRRRouting",nullptr)==nullptr);\n'
        'assert(reload.GetValue("FSR-RR","FloorVirtualAlbedo",nullptr)==nullptr);\n'
        'assert(std::string(reload.GetValue("FSR-RR","FloorHandoverAnchorClamp",""))=="2.5");\n'
        'assert(std::string(reload.GetValue("FSR-RR","FloorHandoverCorrelationMix",""))=="0.6");}\n')
    exe=OUT/'ini_cleanup.exe'
    compile_cpp(cpp, exe)
    subprocess.run([str(exe)],check=True)
    print('PASS: 29 retired keys removed; new keys and unrelated INI values survive save/reload')

if __name__=='__main__':run()
