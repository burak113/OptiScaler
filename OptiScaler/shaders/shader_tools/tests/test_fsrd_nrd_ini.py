"""Execute NRD bridge INI defaults/load/save/reload and the production menu assignment.

Uses the actual CustomOptional, readString/readBool, serializer and key statements.
The separate ini_cleanup fixture retains all 57 retired-key checks unchanged.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
from test_fsrd_nrd_root_restore import function


def unique_line(source, marker):
    lines = [line.strip() for line in source.splitlines() if marker in line]
    assert len(lines) == 1, (marker, lines)
    return lines[0]


def run():
    header = (ROOT/'OptiScaler/Config.h').read_text()
    source = (ROOT/'OptiScaler/Config.cpp').read_text()
    menu = (ROOT/'OptiScaler/menu/menu_common.cpp').read_text()
    startup = (ROOT/'OptiScaler/dllmain.cpp').read_text()
    custom = header[header.index('enum HasDefaultValue'):header.index('constexpr inline int UnboundKey')]
    keys = ('FfxDenoiserNrdBridge', 'FfxDenoiserNrdBridgeEnabled')
    declarations = '\n'.join(unique_line(header, 'CustomOptional<bool> '+key+' ') for key in keys)
    resets = '\n'.join(unique_line(source, key+'.reset();') for key in keys)
    loads = '\n'.join(unique_line(source, key+'.set_from_config(readBool(') for key in keys)
    saves = '\n'.join(unique_line(source, 'GetBoolValue(Instance()->'+key+'.value_for_config())') for key in keys)
    assignment = unique_line(menu, 'config->FfxDenoiserNrdBridgeEnabled ')
    assert assignment == 'config->FfxDenoiserNrdBridgeEnabled = enabled;', assignment
    at = startup.index('if (NrdBridge::StartupEnabled())')
    begin = startup.index('{', at)
    end = startup.index('}', begin)
    force = startup[at:end+1]
    # This is the initial quirk configuration, before the DLL's hook entry point.
    assert startup.index('CheckQuirks(possibleNvidia);') > at
    template = (ROOT/'OptiScaler.ini').read_text()
    assert re.search(r'^NrdBridge=false\s*$', template, re.M)
    assert re.search(r'^NrdBridgeEnabled=true\s*$', template, re.M)
    cpp = r'''
#define SI_NO_CONVERSION
#include "__SIMPLEINI__"
#include <optional>
#include <concepts>
#include <string>
#include <vector>
#include <ranges>
#include <algorithm>
#include <format>
#include <cctype>
#include <iostream>
#include <stdexcept>
__CUSTOM__
CSimpleIniA ini;
bool startupEnabled=false;
namespace NrdBridge { bool StartupEnabled() { return startupEnabled; } }
__SERIALIZER__
struct Config {
 __DECLARATIONS__
 CustomOptional<bool> RestoreComputeSignature{false}, ExtendedStateRestore{false};
 std::vector<std::string> _log;
 static Config* active;
 static Config* Instance() { return active; }
 std::optional<std::string> readString(std::string section,std::string key,bool lowercase=false);
 std::optional<bool> readBool(std::string section,std::string key);
 void load(const std::string& input) {
  ini.Reset(); if(ini.LoadData(input)<0) throw std::runtime_error("INI load");
  __RESETS__
  __LOADS__
 }
 std::string save() {
  __SAVES__
  std::string saved; if(ini.Save(saved)<0) throw std::runtime_error("INI save"); return saved;
 }
};
Config* Config::active=nullptr;
__READSTRING__
__READBOOL__
unsigned checks=0;
void need(bool ok,const char* message) { if(!ok) throw std::runtime_error(message); ++checks; }
void menu(Config* config,bool enabled) { __ASSIGNMENT__ }
void forceRestore() { __FORCE__ }
void roundtrip(const std::string& fixture,bool boot,bool enabled) {
 Config first; Config::active=&first; first.load(fixture);
 need(first.FfxDenoiserNrdBridge.value_or_default()==boot,"startup key load");
 need(first.FfxDenoiserNrdBridgeEnabled.value_or_default()==enabled,"runtime key load");
 auto saved=first.save();
 Config reload; Config::active=&reload; reload.load(saved);
 need(reload.FfxDenoiserNrdBridge.value_or_default()==boot,"startup key survives save/reload");
 need(reload.FfxDenoiserNrdBridgeEnabled.value_or_default()==enabled,"runtime key survives save/reload");
 need(std::string(ini.GetValue("Other","NrdBridge",""))=="untouched","other section is preserved");
 need(std::string(ini.GetValue("FSR-RR","Unrelated",""))=="keep","unrelated key is preserved");
}
int main() try {
 const std::string suffix="Unrelated=keep\n[Other]\nNrdBridge=untouched\n";
 roundtrip("[FSR-RR]\n"+suffix,false,true);
 roundtrip("[FSR-RR]\nNrdBridge=auto\nNrdBridgeEnabled=invalid\n"+suffix,false,true);
 roundtrip("[FSR-RR]\nNrdBridge=TrUe\nNrdBridgeEnabled=FALSE\n"+suffix,true,false);
 for(bool boot:{false,true}) for(bool enabled:{false,true})
  roundtrip(std::string("[FSR-RR]\nNrdBridge=")+(boot?"true":"false")+"\nNrdBridgeEnabled="+(enabled?"true":"false")+"\n"+suffix,boot,enabled);
 Config config; Config::active=&config; config.load("[FSR-RR]\nNrdBridge=true\nNrdBridgeEnabled=true\n");
 menu(&config,false);
 need(!config.FfxDenoiserNrdBridgeEnabled.value_or_default(),"menu toggle applies immediately");
 auto saved=config.save();
 need(saved.find("NrdBridgeEnabled = false")!=std::string::npos,"menu toggle is serialized");
 config.load(saved); need(!config.FfxDenoiserNrdBridgeEnabled.value_or_default(),"menu off survives reload");
 menu(&config,true); saved=config.save(); config.load(saved);
 need(config.FfxDenoiserNrdBridgeEnabled.value_or_default(),"menu on survives reload");
 need(!config.FfxDenoiserNrdBridgeEnabled.value_for_config().has_value(),"runtime default serializes as auto");
 need(config.FfxDenoiserNrdBridge.value_for_config()==true,"startup true remains explicit");
 config.load("[FSR-RR]\n");
 need(!config.FfxDenoiserNrdBridge.value_or_default() && config.FfxDenoiserNrdBridgeEnabled.value_or_default(),"missing keys restore defaults after reload");
 config.RestoreComputeSignature=false; config.ExtendedStateRestore=false;
 startupEnabled=false; forceRestore();
 need(!config.RestoreComputeSignature.value_or_default() && !config.ExtendedStateRestore.value_or_default(),"disabled bridge leaves restore settings alone");
 startupEnabled=true; forceRestore();
 need(config.RestoreComputeSignature.value_or_default() && config.ExtendedStateRestore.value_or_default(),"enabled bridge forces both restore settings before hook startup");
 need(!config.RestoreComputeSignature.value_for_config().has_value() && !config.ExtendedStateRestore.value_for_config().has_value(),"forced restore settings remain volatile");
 std::cout << "PASS: " << checks << " production NRD INI checks\n";
 return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
'''
    replacements = {
        'SIMPLEINI': (ROOT/'external/simpleini/SimpleIni.h').as_posix(),
        'CUSTOM': custom, 'DECLARATIONS': declarations, 'RESETS': resets,
        'LOADS': loads, 'SAVES': saves, 'ASSIGNMENT': assignment, 'FORCE': force,
        'SERIALIZER': function(source, 'std::string GetBoolValue('),
        'READSTRING': function(source, 'std::optional<std::string> Config::readString('),
        'READBOOL': function(source, 'std::optional<bool> Config::readBool('),
    }
    for name, value in replacements.items():
        cpp = cpp.replace('__'+name+'__', value)
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    file, exe = out/'nrd_ini.cpp', out/'nrd_ini.exe'
    file.write_text(cpp)
    compile_cpp(file, exe)
    result = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
    print(result.stdout, end='')
    checks = int(re.search(r'PASS: (\d+)', result.stdout).group(1))
    (out/'result.json').write_text(json.dumps({'native_checks':checks,'python_checks':4,
        'production_ini_keys':['NrdBridge','NrdBridgeEnabled'],
        'scope':'actual optional/parser/serializer/menu statements; existing 57-key cleanup tested separately'})+'\n')


if __name__ == '__main__':
    run()
