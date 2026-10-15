"""Live compute303/pixel36 flag profiles through the same actual PureCommit ABI.

The sealed 300-case PureCommit regression is reused for BOTH independently
poisoned source words. No NRD output RGB is used. --run needs the shared GPU lock.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import sys
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
PRE=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile'
OUT=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/sol_batch/15-nrd-ghosting/tests/pixel-flag'))
NAMES=('FSRDNrdBridgeFlagPixel','FSRDNrdBridgeFlagPixelRoot')

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def fixture_source():
    original=(HERE/'fsrd_nrd_pure_commit_fixture.cpp').read_text()
    changes={
        'static void PureSetFlag(ID3D12Resource* buffer,uint32_t word)':
            'static void PureSetFlag(ID3D12Resource* buffer,uint32_t word,uint32_t sourceWord=303)',
        'static_cast<uint32_t*>(pointer)[303]=word;':
            'static_cast<uint32_t*>(pointer)[sourceWord]=word;static_cast<uint32_t*>(pointer)[sourceWord==303?36:303]=word?0u:1u;',
        'need(capture.Initialize(fixture.device.Get(),error),error.c_str());':
            'need(capture.Initialize(fixture.device.Get(),error),error.c_str());'
            'auto keptRoot=capture.rootPso;auto keptTable=capture.pso;'
            'need(capture.Initialize(fixture.device.Get(),error,36),error.c_str());'
            'need(capture.rootPso.Get()==keptRoot.Get() && capture.pso.Get()==keptTable.Get(),"pixel preparation must retain recorded compute flag PSOs");'
            'auto pixelRoot=capture.pixelRootPso;auto pixelTable=capture.pixelPso;'
            'need(!capture.Initialize(fixture.device.Get(),error,37),"unsupported source word must fail before GPU recording");'
            'need(capture.pixelRootPso.Get()==pixelRoot.Get() && capture.pixelPso.Get()==pixelTable.Get(),"failed preparation must preserve both profiles");error.clear();',
        'for(const auto test:cases)for(const auto coefficient:coefficients)':
            'for(const uint32_t sourceWord:{303u,36u})for(const auto test:cases)for(const auto coefficient:coefficients)',
        'PureSetFlag(first.Get(),test.flag?0u:1u);PureSetFlag(second.Get(),test.flag?0u:1u);':
            'PureSetFlag(first.Get(),test.flag?0u:1u,sourceWord);PureSetFlag(second.Get(),test.flag?0u:1u,sourceWord);',
        'NrdBridge::TitleSignalConstants constants{nullptr,first->GetGPUVirtualAddress()};':
            'NrdBridge::TitleSignalConstants constants{nullptr,first->GetGPUVirtualAddress()};constants.wordIndex=sourceWord;',
        'PureSetFlag(second.Get(),test.flag);': 'PureSetFlag(second.Get(),test.flag,sourceWord);',
        'else PureSetFlag(first.Get(),test.flag);': 'else PureSetFlag(first.Get(),test.flag,sourceWord);',
        'completed==300 && nativeFlags==240 && comparedWords==uint64_t(300)':
            'completed==600 && nativeFlags==480 && comparedWords==uint64_t(600)',
        'pure_commit PASS checks=': 'pixel_flag PASS checks=',
    }
    for before,after in changes.items():
        assert original.count(before)==1, before
        original=original.replace(before,after)
    return original

class CpuProof(unittest.TestCase):
    def test_fixed_pixel_word_36_only(self):
        for name in NAMES:
            source=(PRE/(name+'.hlsl')).read_text()
            self.assertIn('TitlePixelConstants[9].x',source)
            self.assertIn('Store(1212u,',source)
            self.assertNotIn('[75]',source)
            self.assertIn('uint4 TitlePixelConstants[10]',source)
    def test_exact_existing_flag_root_layout(self):
        for name,old in zip(NAMES,('FSRDNrdBridgeFlag','FSRDNrdBridgeFlagRoot')):
            extract=lambda p: ''.join(re.findall(r'"([^\"]*)"',p.read_text().split('cbuffer',1)[0]))
            self.assertEqual(extract(PRE/(name+'.hlsl')),extract(PRE/(old+'.hlsl')))
    def test_dual_profile_regression_keeps_prescribed_matrix(self):
        source=fixture_source()
        self.assertIn('completed==600 && nativeFlags==480',source)
        self.assertIn('sourceWord==303?36:303',source)
        self.assertIn('constants.wordIndex=sourceWord',source)
        self.assertIn('coefficient_bitpatterns=6',source)
        self.assertIn('opaque title alpha',source)

def native():
    sys.path.insert(0,str(HERE.parent))
    from fsrd_toolchain import compile_cpp,dxc
    from build_fsrd_shader import build
    from test_fsrd_nrd_bridge_rr import bounded_run
    import test_fsrd_nrd_pure_commit as pure
    before={str(p):sha(p) for name in ('FSRDNrdBridgeFlag','FSRDNrdBridgeFlagRoot','FSRDNrdBridgePureCommit','FSRDNrdBridgeCommit')
            for p in (PRE/(name+'.hlsl'),PRE/(name+'_Shader.cso'),PRE/(name+'_Shader.h'))}
    for name in NAMES: build(name,dxc())
    compiled={}
    for name in NAMES:
        assembly=(PRE/(name+'_Shader.h')).read_text().split('#endif',1)[0]
        rows=re.findall(r'@dx.op.cbufferLoadLegacy.\w+\(i32 59, %dx.types.Handle %\d+, i32 (\d+)\)',assembly)
        assert rows==['9'],(name,rows)
        values=re.findall(r'extractvalue %dx.types.CBufRet.i32 %\d+, (\d+)',assembly)
        assert values==['0'],(name,values)
        compiled[name]={'source_cbuffer_rows':rows,'source_components':values,'sha256':sha(PRE/(name+'_Shader.cso'))}
    pure.OUT=OUT
    assert OUT.is_dir() and not list(OUT.glob('stage-*.bin'))
    for signal,data in zip(('spec','diff'),pure.stage_data()):data.tofile(OUT/('stage-'+signal+'.bin'))
    for variant in range(5):
        for signal,data in zip(('spec','diff'),pure.title_data(variant)):data.tofile(OUT/('title%d-'%variant+signal+'.bin'))
    for mode in (0,1):
        for signal,rr,title in zip(('spec','diff'),pure.stage_data(),pure.title_data(0)):
            pure.encoded(rr,mode,title[...,3]).tofile(OUT/('expected%d-'%mode+signal+'.bin'))
    original=(HERE/'fsrd_nrd_conversion_fixture.cpp').read_text()
    prefix=original.split('static ULONG References(')[0]
    marker='#include "production_nrd_pass.cpp"'
    assert prefix.count(marker)==1
    includes='#include "'+(HERE/'dx12_shader_test_support.h').as_posix()+'"\n'
    includes+='#include "misc/NrdBridgeOwned_Dx12.h"\n#include "FSRDNrdSignalConstants_Dx12.h"\n'
    source=OUT/'pixel_flag.cpp';source.write_text(prefix.replace(marker,includes)+fixture_source())
    exe=OUT/'pixel_flag.exe'
    compile_cpp(source,exe,('d3d12.lib','dxgi.lib','d3dcompiler.lib'),
                (OUT,HERE,PRE.parent,ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/streamline'))
    text,peak,elapsed,log=bounded_run([str(exe),str(OUT)],OUT/'native')
    print(text,end='')
    assert 'pixel_flag PASS' in text and 'debug_errors=0 debug_warnings=0' in text
    assert before=={p:sha(p) for p in before}
    result=dict(native_stdout=text,compiled_proofs=compiled,legacy_assets_unchanged=before,
                native_seconds=elapsed,peak_resident_bytes=peak,native_log=str(log),
                scope='actual GPU flag capture and PureCommit only; no provider, title execution or graphics hook eligibility claim')
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',action='store_true');args=parser.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CpuProof))
    if not result.wasSuccessful():raise SystemExit(1)
    if args.run:native()
