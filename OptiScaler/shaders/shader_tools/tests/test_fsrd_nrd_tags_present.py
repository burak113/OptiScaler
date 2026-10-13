"""Execute production Streamline MV routing and Present startup/test gating."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp


def run():
    sl = (ROOT/'OptiScaler/hooks/Streamline_Hooks.cpp').read_text()
    overlay = (ROOT/'OptiScaler/menu/menu_overlay_dx.cpp').read_text()
    pattern = (r'if \(renderApi == sl::RenderAPI::eD3D12\)\s*\{\s*'
               r'probeSLResourceTag\([^;]+;\s*'
               r'if \(NrdBridge::StartupEnabled\(\) && (?:tags|resources)\[i\]\.type == sl::kBufferTypeMotionVectors\)\s*'
               r'NrdBridge::OnTitleTag\([^;]+;')
    blocks = re.findall(pattern,sl)
    assert len(blocks)==2, blocks
    blocks = [block+'\n}' for block in blocks]
    present = [line.strip() for line in overlay.splitlines() if 'NrdBridge::OnPresent();' in line]
    assert len(present)==1, present
    # NGX motion tag 3660 is different from the SL NRD tag 44135 in the capture.
    # Prevent an unrelated title-tag routing path from silently overwriting it.
    other = []
    for path in (ROOT/'OptiScaler/inputs').glob('*.cpp'):
        if 'NrdBridge::OnTitleTag(' in path.read_text():
            other.append(path.name)
    assert not other, other
    cpp = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <cstdint>
#include <string>
#include <iostream>
#include <stdexcept>
unsigned checks=0;
void need(bool ok,const char* message) { if(!ok) throw std::runtime_error(message); ++checks; }
namespace sl {
 enum class RenderAPI { eD3D12,eD3D11,eVulkan };
 enum { kBufferTypeMotionVectors=1,kBufferTypeDepth=2,kBufferTypeScalingInputColor=3 };
}
struct Resource { void* native; };
struct Tag { unsigned type; Resource* resource; };
enum class RRTagSource { SetTag,SetTagForFrame };
void probeSLResourceTag(Tag,uint32_t,uint32_t,RRTagSource) {}
bool boot=false;
namespace NrdBridge {
 unsigned tags=0,presents=0; ID3D12Resource* last=nullptr; ID3D12GraphicsCommandList* lastList=nullptr;
 bool StartupEnabled() { return boot; }
 void OnTitleTag(ID3D12GraphicsCommandList* list,const char* name,ID3D12Resource* resource) {
  need(std::string(name)=="MotionVectors","only Streamline motion tag name routed");
  ++tags; last=resource; lastList=list;
 }
 void OnPresent() { ++presents; }
}
void tag(bool forFrame,sl::RenderAPI api,unsigned kind,Resource* resource) {
 const auto renderApi=api; uint32_t viewport=0,frame=7,i=0;
 void* cmdBuffer=reinterpret_cast<void*>(9); Tag tags[]={{kind,resource}},resources[]={{kind,resource}};
 if(forFrame) { __FOR_FRAME__ } else { __SET_TAG__ }
}
void present(UINT Flags) { __PRESENT__ }
int main() try {
 Resource motion{reinterpret_cast<void*>(44135)},ngxMotion{reinterpret_cast<void*>(3660)};
 for(bool forFrame:{false,true}) {
  boot=false; const auto before=NrdBridge::tags;
  tag(forFrame,sl::RenderAPI::eD3D12,sl::kBufferTypeMotionVectors,&motion);
  need(NrdBridge::tags==before,"disabled bridge has no MV callbacks");
  boot=true;
  tag(forFrame,sl::RenderAPI::eD3D11,sl::kBufferTypeMotionVectors,&motion);
  tag(forFrame,sl::RenderAPI::eVulkan,sl::kBufferTypeMotionVectors,&motion);
  tag(forFrame,sl::RenderAPI::eD3D12,sl::kBufferTypeDepth,&ngxMotion);
  tag(forFrame,sl::RenderAPI::eD3D12,sl::kBufferTypeScalingInputColor,&ngxMotion);
  need(NrdBridge::tags==before,"wrong API and non-motion tags cannot change NRD MV");
  tag(forFrame,sl::RenderAPI::eD3D12,sl::kBufferTypeMotionVectors,&motion);
  need(NrdBridge::tags==before+1 && uintptr_t(NrdBridge::last)==44135,"SL NRD motion identity is routed exactly once");
  need(uintptr_t(NrdBridge::lastList)==9,"tag retains its native command-list identity");
  tag(forFrame,sl::RenderAPI::eD3D12,sl::kBufferTypeMotionVectors,nullptr);
  need(NrdBridge::tags==before+2 && !NrdBridge::last,"SL motion untag is routed as null");
 }
 boot=false; present(0); present(DXGI_PRESENT_TEST);
 need(NrdBridge::presents==0,"disabled bridge has no Present callbacks");
 boot=true; present(DXGI_PRESENT_TEST); present(DXGI_PRESENT_TEST|DXGI_PRESENT_DO_NOT_WAIT);
 need(NrdBridge::presents==0,"DXGI_PRESENT_TEST cannot advance bridge frame/history");
 present(0); present(DXGI_PRESENT_DO_NOT_WAIT);
 need(NrdBridge::presents==2,"real Present invokes bridge exactly once per call");
 std::cout<<"PASS: "<<checks<<" production SL tag/Present checks\n"; return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
'''
    cpp = cpp.replace('__SET_TAG__',blocks[0]).replace('__FOR_FRAME__',blocks[1]).replace('__PRESENT__',present[0])
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True,exist_ok=True)
    source,exe = out/'nrd_tags.cpp',out/'nrd_tags.exe'
    source.write_text(cpp)
    compile_cpp(source,exe)
    result = subprocess.run([str(exe)],check=True,capture_output=True,text=True)
    print(result.stdout,end='')
    checks = int(re.search(r'PASS: (\d+)',result.stdout).group(1))
    (out/'result.json').write_text(json.dumps({'native_checks':checks,'python_checks':3,
        'scope':'actual SL callback blocks and Present guard; no live game or real slSetTag invocation'})+'\n')


if __name__ == '__main__':
    run()
