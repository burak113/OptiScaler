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
sys.path.insert(0,str(HERE))
from test_fsrd_nrd_root_restore import function
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
            'need(!capture.Prepared(303)&&!capture.Prepared(36)&&!capture.Prepared(37),"fresh capture owns no prepared profile");'
            'need(capture.Initialize(fixture.device.Get(),error,303),error.c_str());'
            'need(capture.Prepared(303)&&!capture.Prepared(36),"compute word first use prepares exactly its own table/direct pair");'
            'auto keptRoot=capture.rootPso;auto keptTable=capture.pso;auto keptDirect=capture.directRoot;auto keptRootTable=capture.root;'
            'need(capture.Initialize(fixture.device.Get(),error,36),error.c_str());'
            'need(capture.Prepared(303)&&capture.Prepared(36)&&capture.pso.Get()==keptTable.Get()&&capture.rootPso.Get()==keptRoot.Get()&&'
            'capture.root.Get()==keptRootTable.Get()&&capture.directRoot.Get()==keptDirect.Get(),"pixel profile switch retains the recorded compute flag PSOs and roots");'
            'auto pixelRoot=capture.pixelRootPso;auto pixelTable=capture.pixelPso;auto pixelDirect=capture.pixelDirectRoot;auto pixelRootTable=capture.pixelRoot;'
            'need(!capture.Initialize(fixture.device.Get(),error,37),"unsupported source word must fail before GPU recording");'
            'need(capture.Prepared(303)&&capture.Prepared(36)&&capture.pixelRootPso.Get()==pixelRoot.Get()&&capture.pixelPso.Get()==pixelTable.Get()&&'
            'capture.pixelRoot.Get()==pixelRootTable.Get()&&capture.pixelDirectRoot.Get()==pixelDirect.Get(),"failed preparation must preserve both profiles");error.clear();',
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
    def test_write_debug_prepares_accepted_word_before_record(self):
        body=function((ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgePass_Dx12.cpp').read_text(),'bool ConversionPass::WriteDebug(')
        self.assertIn('flagCapture.Initialize(owner->device.Get(), error, titleConstants.wordIndex)',body)
        self.assertIn('flagCapture.Prepared(titleConstants.wordIndex)',body)
        self.assertLess(body.index('Prepared(titleConstants.wordIndex)'),body.index('guard.admit'),
                        'accepted-word preparation must precede the deferred commit')
        self.assertIn('flagCapture.Record(prepared.list, prepared.titleConstants, prepared.slot->flag)',body)
        self.assertNotIn('flagCapture.Initialize(owner->device.Get(), error))',body,
                         'default-word preparation would miss the accepted pixel word36 profile')
    def test_prepared_covers_both_root_forms_and_words(self):
        header=(PRE.parent/'FSRDNrdSignalConstants_Dx12.h').read_text()
        prepared=function(header,'bool Prepared(uint32_t wordIndex) const noexcept')
        self.assertIn('wordIndex == 36',prepared)
        self.assertIn('wordIndex == 303',prepared)
        self.assertIn('pixelRoot && pixelDirectRoot && pixelPso && pixelRootPso',prepared)
        self.assertIn('root && directRoot && pso && rootPso',prepared)
        self.assertIn('return false;',prepared)
        record=function(header,'void Record(ID3D12GraphicsCommandList* list, const TitleSignalConstants& constants,')
        self.assertIn('const bool pixel = constants.wordIndex == 36;',record)
        self.assertIn('list->SetPipelineState(pixel ? pixelPso.Get() : pso.Get());',record)
        self.assertIn('list->SetPipelineState(pixel ? pixelRootPso.Get() : rootPso.Get());',record)

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
    OUT.mkdir(parents=True,exist_ok=True)
    assert not list(OUT.glob('stage-*.bin'))
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
