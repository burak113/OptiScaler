"""Lead regression for real host Hold control flow and snapshot/copy contracts.

This is a compiled control-flow fixture, not a live game or GPU-copy IQ test.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT=Path(__file__).resolve().parents[4]

def body(text,signature):
    start=text.index(signature);opening=text.index('{',start);depth=1;end=opening+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]

def run():
    source=(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp').read_text()
    prepare=body(source,'    ID3D12Resource* PrepareComparePresentation(')
    copy=body(source,'    bool CopyCompareTexture(')
    compose=body(source,'    void DispatchComposition(')
    assert 'm_compareSnapshotsReady = capturedA && capturedB;' in compose
    assert compose.index('ReblurSkin(cmdList, desc);') < compose.index('if (compare == 1u || compare == 4u)')
    assert 'capturedB = CaptureCompare(cmdList,CompositionColor(),m_compareSnapshotB);' in compose
    assert compose.count('capturedB = CaptureCompare(')==3
    assert 'compare != m_compareView' in compose and 'm_compareFrozenValid = false;' in compose
    assert 'm_comparePresent.Reset(); m_compareFrozen.Reset();' in compose
    assert copy.index('RetainComputeDispatch') < copy.index('CopyTextureRegion')
    assert 'CopyTextureRegion(&target,0,0,0,&source,&box)' in copy
    assert 'sourceDesc.Width < targetDesc.Width' in copy
    assert prepare.index('EnsureComparePresentation') < prepare.index('if (hold && m_compareFrozenValid)')
    cpp=r'''
#include <cassert>
#include <cstdio>
#include <cstdint>
struct ID3D12GraphicsCommandList {};
struct ID3D12Resource { unsigned content=0; };
struct Ptr { ID3D12Resource* p;ID3D12Resource* Get()const{return p;}explicit operator bool()const{return p!=nullptr;} };
struct Fixture
{
    ID3D12Resource a,b,present,frozen;
    Ptr m_compareSnapshotA{&a},m_compareSnapshotB{&b},m_comparePresent{&present},m_compareFrozen{&frozen};
    bool m_compareFrozenValid=false,m_compareSnapshotsReady=true,copySucceeds=true;
    unsigned width=0,height=0,dispatches=0,nextContent=1;
    void EnsureComparePresentation(unsigned w,unsigned h)
    {if(width!=w || height!=h){width=w;height=h;m_compareFrozenValid=false;}}
    void DispatchCompare(ID3D12GraphicsCommandList*,unsigned w,unsigned h,bool,float)
    {EnsureComparePresentation(w,h);++dispatches;present.content=nextContent++;}
    bool CopyCompareTexture(ID3D12GraphicsCommandList*,ID3D12Resource* from,ID3D12Resource* to)
    {if(!copySucceeds)return false;to->content=from->content;return true;}
__PREPARE__
};
int main()
{
    Fixture f;ID3D12GraphicsCommandList cmd;
    auto p=f.PrepareComparePresentation(&cmd,2560,1440,false,.5f,false);
    assert(p==&f.present && p->content==1 && f.dispatches==1);
    p=f.PrepareComparePresentation(&cmd,2560,1440,false,.5f,true);
    assert(p==&f.frozen && p->content==2 && f.dispatches==2);
    // New canonical camera/SR/input frames change what a new composite WOULD contain.
    f.nextContent=999;
    for(int i=0;i<8;++i) {p=f.PrepareComparePresentation(&cmd,2560,1440,true,.75f,true);assert(p->content==2);}
    assert(f.dispatches==2);
    p=f.PrepareComparePresentation(&cmd,1920,1080,false,.5f,true);
    assert(p->content==999 && f.width==1920 && f.height==1080 && f.dispatches==3);
    p=f.PrepareComparePresentation(&cmd,1920,1080,false,.5f,false);
    assert(p==&f.present && !f.m_compareFrozenValid && p->content==1000);
    f.m_compareSnapshotsReady=false;
    assert(!f.PrepareComparePresentation(&cmd,1920,1080,false,.5f,false));
    assert(f.dispatches==4);
    f.m_compareSnapshotsReady=true;f.copySucceeds=false;
    assert(!f.PrepareComparePresentation(&cmd,1920,1080,false,.5f,true));
    assert(!f.m_compareFrozenValid);
    assert(!f.PrepareComparePresentation(nullptr,1920,1080,false,.5f,true));
    assert(!f.PrepareComparePresentation(&cmd,0,1080,false,.5f,true));
    std::puts("actual Hold method: changing frames remain frozen, resize invalidates, release resumes, copy/admission failure closed PASS");
}
'''.replace('__PREPARE__',prepare)
    output=Path(os.environ['FSRD_GPU_TEST_OUTPUT']);output.mkdir(parents=True,exist_ok=True)
    path=output/'hold_control.cpp';path.write_text(cpp)
    exe=output/'hold_control.exe';compile_cpp(path,exe)
    subprocess.run([str(exe)],check=True)
    (output/'result.json').write_text(json.dumps(dict(status='PASS',scope='actual extracted host method with modeled resources; structural checks pin all four snapshot pairs, prefix leases and ROI copy extent; separate GPU test covers shader sampling'),indent=2))

if __name__=='__main__':run()
