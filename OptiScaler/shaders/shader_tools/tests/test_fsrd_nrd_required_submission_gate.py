"""CPU proof of fatal required-RR denial at the actual queue forwarding gates.

Uses the actual lease/Birth/GUID headers and extracted FG/base/selector/survey
functions. Optional recorder/FG/trace effects and COM objects are explicit spies.
No native GPU submission, physical Release coverage, or image-quality claim.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(os.environ.get('FSRD_NRD_PRODUCTION_ROOT', Path(__file__).resolve().parents[4]))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import compile_cpp
from test_recorded_compute_submission import fake_com
from test_fsrd_submission_transactions import definition as function

DRIVER = r'''
void cleanCase() {
 denyAllocations=false;RecordedComputeLease::gUntrackedRequiredSubmissionFailure.store(S_OK);
 resetRegistry();State::Instance().currentFG=nullptr;FrameSurvey::recorder=false;
 _notFoundCmdLists.clear();for(auto& row:_resCmdList)row.clear();
}
int main()try {
 SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);spyRegistryChecks=false;
 ComPtr<FakeDevice> device;device.Attach(new FakeDevice);
 ComPtr<SpyList> source;source.Attach(new SpyList(device.Get()));
 ComPtr<FakeQueue> queue;queue.Attach(new FakeQueue(device.Get()));
 ID3D12CommandList* list=source.Get();FixtureFG fg;fg.active=true;
 cleanCase();need(SUCCEEDED(RecordedComputeLease::RequiredSubmissionFailure()),"new process has no fatal denial");
 const auto first=queue->executions;ResTrack_Dx12::hkSurveyExecuteCommandLists(queue.Get(),1,&list);
 need(queue->executions==first+1,"healthy no-participant FG-null queue forwards exactly once");
 coveredFixtureList=static_cast<ID3D12GraphicsCommandList*>(source.Get());
 need(!NrdBridgeNativeBirth::ObserveReleaseCoverage(reinterpret_cast<IUnknown*>(uintptr_t(0xfeed0000))),"coverage adapter rejects every foreign opaque address without COM");
 configureMetadataBirth();const auto born=NrdBridgeNativeBirth::Prepare(source.Get());
 need(born&&born->CacheAdmissible()&&!born->RecordingMayExist(),"actual GUID protocol publishes unmarked list birth");
 need(coverageAccepted==2&&coverageRejected==1,"actual GUID Prepare checks exact owned typed and canonical Release entries via explicit adapter");
 const auto queries=source->queries;need(!HasRetainedSubmissionParticipant(1,&list)&&source->queries==queries,"healthy proven unmarked list takes exact native fastnegative");
 unsigned cases=0;
 for(unsigned route=0;route<3;++route) {
  cleanCase();source->failIdentity=true;
  if(route==1){State::Instance().currentFG=&fg;_resCmdList[0][FixtureResource]=list;}
  const auto before=queue->executions,qi=source->queries,submitted=FrameSurvey::submitted.load();
  RecordedComputeLease::FailUntrackedRequiredSubmission(E_OUTOFMEMORY);
  need(HasRetainedSubmissionParticipant(1,&list),"fatal denial precedes native unmarked selector bypass");
  RecordedComputeLease::SubmissionDecision decision;
  denyAllocations=true;
  const auto intent=ResTrack_Dx12::BeforeComputeSubmission(queue.Get(),1,&list,&decision);
  if(route==2)ResTrack_Dx12::hkSurveyExecuteCommandLists(queue.Get(),1,&list);
  else ResTrack_Dx12::hkExecuteCommandLists(queue.Get(),1,&list);
  denyAllocations=false;
  need(!intent&&!decision.allowed&&decision.orderingFailure==E_OUTOFMEMORY,"fatal untracked RR failure explicitly denies caller decision");
  need(queue->executions==before&&source->queries==qi&&FrameSurvey::submitted==submitted,"FG/base/survey denial has no native Execute, identity probe or recorder publication");
  need(RecordedComputeLease::GetRegistry().completionFailed,"explicit DenySubmission latches ledger uncertainty");
  source->failIdentity=false;++cases;
 }
 for(bool withFG:{false,true}) {
  cleanCase();if(withFG){State::Instance().currentFG=&fg;_resCmdList[0][FixtureResource]=list;}
  const auto before=queue->executions;RRTraceFence::trip=true;
  ResTrack_Dx12::hkExecuteCommandLists(queue.Get(),1,&list);RRTraceFence::trip=false;
  need(queue->executions==before&&FAILED(RecordedComputeLease::RequiredSubmissionFailure()),"latch raised after BeforeComputeSubmission is rechecked immediately before FG/base native Execute");
  ++cases;
 }
 cleanCase();RecordedComputeLease::FailUntrackedRequiredSubmission(E_ABORT);
 RecordedComputeLease::FailUntrackedRequiredSubmission(E_OUTOFMEMORY);
 need(RecordedComputeLease::RequiredSubmissionFailure()==E_ABORT,"fatal process latch preserves first failing HRESULT");
 RecordedComputeLease::SubmissionDecision denied;denied.allowed=false;denied.orderingFailure=E_INVALIDARG;
 need(!RequiredComputeSubmissionAllowed(&denied)&&denied.orderingFailure==E_INVALIDARG,"queue gate preserves an earlier caller decision failure");
 cleanCase();const auto before=queue->executions;ID3D12CommandList* batch[2]={list,nullptr};
 RecordedComputeLease::FailUntrackedRequiredSubmission(S_OK);
 need(RecordedComputeLease::RequiredSubmissionFailure()==E_FAIL,"nonfailure latch argument becomes explicit E_FAIL");
 denyAllocations=true;ResTrack_Dx12::hkSurveyExecuteCommandLists(queue.Get(),2,batch);denyAllocations=false;
 need(queue->executions==before,"fatal batch is denied whole, with unknown identity and no filtering");
 need(deniedAllocations==0,"all warmed fatal gates remain allocation-free under forced OOM");
 need(!FrameSurvey::metadataFailures,"actual GUID metadata stays healthy");
 cleanCase();auto lease=std::make_shared<unsigned>(1);unsigned admissionsBefore=0,admissionsPublished=0;
 RecordedComputeLease::SubmissionCallbacks callbacks;
 callbacks.beforeSubmit=[&](const auto&){need(NrdBridgeDescriptorAdmission::SubmissionHeldByCurrentThread(),"actual Before callback holds native descriptor admission gate");++admissionsBefore;return true;};
 callbacks.fencePublished=[&](const auto&,const auto&){need(NrdBridgeDescriptorAdmission::SubmissionHeldByCurrentThread(),"already-submitted lease publication precedes admission reopening");++admissionsPublished;};
 track(source.Get(),lease,callbacks);const auto admissionBefore=queue->executions;
 o_ExecuteCommandLists=+[](ID3D12CommandQueue* q,UINT n,ID3D12CommandList* const* commands){need(NrdBridgeDescriptorAdmission::SubmissionHeldByCurrentThread(),"actual original Execute remains inside descriptor admission gate");OriginalExecute(q,n,commands);};
 ResTrack_Dx12::hkExecuteCommandLists(queue.Get(),1,&list);o_ExecuteCommandLists=OriginalExecute;
 need(queue->executions==admissionBefore+1&&admissionsBefore==1&&admissionsPublished==1,"retained participant forwards once with exact Before/Execute/After gate scope");
 need(!NrdBridgeDescriptorAdmission::SubmissionHeldByCurrentThread()&&NrdBridgeDescriptorAdmission::Healthy(),"successful queue returns with admission reopened and healthy");
 cleanCase();track(source.Get(),lease);const auto forbiddenBefore=queue->executions;
 {NrdBridgeDescriptorAdmission::Mutation activeWriter(true);need(activeWriter.Acquired(),"actual native writer admitted before nested-submit negative");ResTrack_Dx12::hkExecuteCommandLists(queue.Get(),1,&list);}
 need(queue->executions==forbiddenBefore&&!NrdBridgeDescriptorAdmission::Healthy()&&FAILED(RecordedComputeLease::RequiredSubmissionFailure()),"reentrant participant cannot deadlock or execute; failure is globally latched");
 std::cout<<J{{"checks",checks.load()},{"fatal_route_cases",cases},{"descriptor_admission_cases",2},{"GPU_submissions",0},
  {"scope","actual queue/selector/Before helper and ledger/Birth/GUID headers; fake COM and explicit FG/recorder/optional trace spies"}}.dump()<<'\n';return 0;
}catch(const std::exception& e){denyAllocations=false;std::cerr<<e.what()<<'\n';return 1;}
'''


def prepare(output):
    source = (ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    signatures = ('static bool RequiredComputeSubmissionAllowed(',
                  'std::shared_ptr<RecordedComputeLease::Submission> ResTrack_Dx12::BeforeComputeSubmission(',
                  'void ResTrack_Dx12::hkExecuteCommandLists(',
                  'static bool HasRetainedSubmissionParticipant(',
                  'void ResTrack_Dx12::hkSurveyExecuteCommandLists(')
    bodies = [function(source, signature) for signature in signatures]
    # Reuse ABI/FG/recorder adapters, not another handwritten queue implementation.
    fixture = (HERE/'fsrd_submission_transaction_fixture.cpp').read_text().split('struct Domain {', 1)[0]
    trace = '''namespace RRTraceFence { inline bool trip=false;
inline int BeforeSubmission(ID3D12CommandQueue*,UINT,ID3D12CommandList* const*) {
 if(trip)RecordedComputeLease::FailUntrackedRequiredSubmission(E_OUTOFMEMORY);return 0; }
inline void AfterSubmission(ID3D12CommandQueue*,int) {} }'''
    needle = '#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/RRTraceFence.h"'
    assert fixture.count(needle) == 1
    fixture = fixture.replace(needle, trace)
    fixture = fixture.replace('#include "__ROOT__/OptiScaler/misc/RecordedComputeLease_Dx12.h"',
        '#include "__ROOT__/OptiScaler/misc/RecordedComputeLease_Dx12.h"\n#include "__ROOT__/OptiScaler/misc/NrdBridgeDescriptorAdmission_Dx12.h"', 1)
    coverage = 'namespace NrdBridgeNativeBirth {bool ObserveReleaseCoverage(IUnknown*) noexcept {return false;}}'
    assert fixture.count(coverage) == 1
    fixture = fixture.replace(coverage, '''IUnknown* coveredFixtureList=nullptr;unsigned coverageAccepted=0,coverageRejected=0;
namespace NrdBridgeNativeBirth {bool ObserveReleaseCoverage(IUnknown* object) noexcept {
 if(object&&object==coveredFixtureList){++coverageAccepted;return true;}++coverageRejected;return false;}}''', 1)
    # This CPU fixture never enters SDK-owned recording scopes.
    fixture = fixture.replace('bool Internal() noexcept {return false;}',
                              'bool Internal() noexcept {return false;} bool OwnedRelease() noexcept {return false;}', 1)
    sdk = Path(os.environ.get('FSRD_D3D12_SDK_HEADER',
        r'C:/Program Files (x86)/Windows Kits/10/Include/10.0.26100.0/um/d3d12.h')).read_text()
    declaration = 'static bool HasRetainedSubmissionParticipant(UINT,ID3D12CommandList* const*) noexcept;\n'
    generated = fixture.replace('__ROOT__', ROOT.as_posix()).replace('__PRODUCTION__', declaration+'\n'.join(bodies))
    generated = generated.replace('__FAKE_COM__', fake_com(sdk))+DRIVER
    output.mkdir(parents=True, exist_ok=True)
    path = output/'required_submission_gate.cpp'
    path.write_text(generated)
    metadata = {'production_root': str(ROOT), 'production_bodies_sha256': {
        signature: hashlib.sha256(body.encode()).hexdigest() for signature, body in zip(signatures, bodies)},
        'descriptor_admission_header_sha256': hashlib.sha256((ROOT/'OptiScaler/misc/NrdBridgeDescriptorAdmission_Dx12.h').read_bytes()).hexdigest()}
    (output/'source.json').write_text(json.dumps(metadata, indent=2)+'\n')
    return path, metadata


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15a-motion/required-submission-gate'))
    source, metadata = prepare(output)
    if args.prepare_only:
        print(json.dumps(metadata))
        return
    exe = output/'required_submission_gate.exe'
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'bcrypt.lib'), (ROOT/'external/nlohmann',))
    process = subprocess.run([str(exe)], capture_output=True, text=True,
                             creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (output/'native.stdout.log').write_text(process.stdout)
    (output/'native.stderr.log').write_text(process.stderr)
    process.check_returncode()
    result = json.loads(process.stdout)
    result.update(metadata)
    (output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    run()
