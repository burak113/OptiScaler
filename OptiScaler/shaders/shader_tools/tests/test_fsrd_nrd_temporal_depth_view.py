"""CPU proof of the production native Temporal t4 view admission; no COM/GPU calls."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[4]
OUT=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/sol_batch/15a-motion/tests/temporal-depth-view'))

DRIVER=r'''
#include <iostream>
#include <stdexcept>
unsigned checks=0;
void need(bool value,const char* name){++checks;if(!value)throw std::runtime_error(name);}
int main()try{
 FrameSurvey::BoundResource valid{};valid.resource=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x12340));
 valid.kind=D3D12_DESCRIPTOR_RANGE_TYPE_SRV;valid.viewFormat=DXGI_FORMAT_R32_FLOAT;
 auto& d=valid.description;d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Format=DXGI_FORMAT_R32_FLOAT;
 d.Width=1505;d.Height=847;d.MipLevels=1;d.DepthOrArraySize=1;d.SampleDesc.Count=1;d.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
 const auto supports=[](const auto& view){return NrdBridge::NativeTemporalDepthViewSupported(view,1505,847);};
 need(supports(valid),"attested single-mip/slice Temporal t4 format and extent");
 auto v=valid;v.resource=nullptr;need(!supports(v),"missing resource");
 v=valid;v.kind=D3D12_DESCRIPTOR_RANGE_TYPE_UAV;need(!supports(v),"UAV is not the native t4 SRV");
 v=valid;v.kind=D3D12_DESCRIPTOR_RANGE_TYPE_CBV;need(!supports(v),"CBV cannot masquerade as depth");
 v=valid;v.viewFormat=DXGI_FORMAT_R32_TYPELESS;need(!supports(v),"untyped view rejected");
 v=valid;v.viewFormat=DXGI_FORMAT_R16_FLOAT;need(!supports(v),"different typed view rejected");
 v=valid;v.subresource=1;need(!supports(v),"nonzero selected mip rejected");
 v=valid;v.subresource=2;need(!supports(v),"nonzero selected array slice rejected");
 v=valid;v.description.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;need(!supports(v),"buffer rejected");
 v=valid;v.description.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE3D;need(!supports(v),"3D texture rejected");
 v=valid;v.description.Format=DXGI_FORMAT_R32_TYPELESS;need(!supports(v),"typeless resource cannot use synthesized format");
 v=valid;v.description.Format=DXGI_FORMAT_R16_FLOAT;need(!supports(v),"different resource format rejected");
 v=valid;v.description.Width=1504;need(!supports(v),"width mismatch rejected");
 v=valid;v.description.Height=846;need(!supports(v),"height mismatch rejected");
 v=valid;v.description.MipLevels=2;need(!supports(v),"mipmapped resource with mip0 view still rejected conservatively");
 v=valid;v.description.MipLevels=0;need(!supports(v),"unspecified mip chain rejected");
 v=valid;v.description.DepthOrArraySize=2;need(!supports(v),"array resource rejected");
 v=valid;v.description.SampleDesc.Count=2;need(!supports(v),"multisample resource rejected");
 v=valid;v.description.SampleDesc.Count=0;need(!supports(v),"invalid sample count rejected");
 v=valid;v.description.Flags=D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE;need(!supports(v),"SRV-denied resource rejected");
 v=valid;v.description.Width=0;need(!NrdBridge::NativeTemporalDepthViewSupported(v,0,847),"zero width rejected even when metadata matches");
 v=valid;v.description.Height=0;need(!NrdBridge::NativeTemporalDepthViewSupported(v,1505,0),"zero height rejected even when metadata matches");
 need(supports(valid),"negative copies leave original legal metadata intact");
 std::cout<<"{\"checks\":"<<checks<<",\"native_calls\":0,\"scope\":\"actual extracted metadata helper; opaque non-COM resource\"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    header=(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdNativeTemporalConstants_Dx12.h').read_text()
    begin=header.index('inline bool NativeTemporalDepthViewSupported(')
    end=header.index('\n}\n',begin)+3
    helper=header[begin:end]
    source='#include "'+(ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.h').as_posix()+'"\nnamespace NrdBridge {\n'+helper+'\n}\n'+DRIVER
    OUT.mkdir(parents=True,exist_ok=True);fixture=OUT/'depth_view.cpp';fixture.write_text(source)
    if args.prepare_only:print(json.dumps({'prepared':True,'production_helper_bytes':len(helper)}));return
    sys.path.insert(0,str(Path(__file__).parent.parent));from fsrd_toolchain import compile_cpp
    exe=OUT/'depth_view.exe';compile_cpp(fixture,exe,(),(ROOT/'OptiScaler',))
    result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=20)
    (OUT/'native.log').write_text(result.stdout+result.stderr);print(result.stdout,end='');print(result.stderr,end='',file=sys.stderr);result.check_returncode()
    values=json.loads(result.stdout);assert values['checks']==23 and values['native_calls']==0
    report=Path('E:/FSRD/sol_batch/15a-motion/temporal-depth-view-tests.json');report.write_text(json.dumps(values,indent=2))

if __name__=='__main__':main()
