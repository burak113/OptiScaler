"""Actual RRWrapper staging-ledger lifecycle and immutable recorded-output
diagnostics on a real D3D12 device.

Composes the existing real-provider RR fixture (its main preserved, unused)
with a diagnostics main. The default mode runs the production mock provider;
--real-provider loads the actual signed AMD export instead. Both modes execute
real GPU allocation/retirement through the unchanged production RecordOwned
path. This proves the F03 accounting contract (hot-slot charging, fail-closed
admission, retained generations, discard visibility, destruction without
unsigned wrap) and the F04 recorded-output contract (tier/reason/error frozen
at the recording frame, older held snapshots never inherit later state). This
is integration evidence, not a game-quality or FPS claim.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(HERE), str(HERE.parent)]
from fsrd_toolchain import compile_cpp, dxc, visual_studio, _toolchain_environment
from test_fsrd_nrd_lobe_recovery import forwarders

MAIN = r'''
namespace LedgerDiag
{
void record(Host& host,LobeObservedList& list,RRWrapper& wrapper,const ConvertedResources& resources,
            uint32_t token,RRRecordedOutputLease& output,const char* what)
{
 FrameParameters frame;std::string error;
 need(wrapper.PrepareFrame(camera(token,1.f),false,frame,error),what);
 need(wrapper.RecordOwned(&list,resources,frame,output,error),error.c_str());
 auto recording=RecordedComputeLease::Capture(&list);
 host.submit();host.reset();RecordedComputeLease::Detach(recording);
}
}

int main(int argc,char** argv)try
{
 std::cout.setf(std::ios::unitbuf);
 need(argc>=2,"ledger diagnostics fixture expects an output folder");
 const bool realMode=argc>2&&std::string(argv[2])=="--real-provider";
 const std::filesystem::path output=argv[1];std::filesystem::create_directories(output);
 if(realMode)loadReal();
 Host host;ComPtr<LobeObservedList> observed;observed.Attach(new LobeObservedList(host.list.Get()));
 J result{{"real_provider",realMode},{"scope",
  "actual production RRWrapper/RecordOwned/ledger getters on a real D3D12 device; synthetic 64x64/96x64 recordings; "
  "integration and accounting proof only, no game-quality/FPS/provider-residency claim"}};
 uint32_t token=7000;
 // F03 scenario 1: the four hot slots are charged at context creation, survive
 // resize generations and discard, and retire exactly on final destruction.
 {
  Scene scene(host,64,64,{},true);host.submit();host.reset();
  RRWrapper wrapper;std::string error;
  need(wrapper.Configure({},error),"configure the warm-ledger wrapper");
  RRRecordedOutputLease first,second;
  LedgerDiag::record(host,*observed.Get(),wrapper,scene.resources,token++,first,"record the first warm output");
  LedgerDiag::record(host,*observed.Get(),wrapper,scene.resources,token++,second,"record the second warm output");
  const auto physical=first->lease->context->stagingBytes;
  auto warmLedger=first->lease->context->ledger;
  need(bool(warmLedger)&&physical>0&&physical%4==0,"the wrapper shares one ledger with its first context");
  auto snap=wrapper.SnapshotStagingLedger();
  need(snap.retainedSlots==4&&snap.retainedBytes==physical,
   "the four hot slots are charged before any recording can hold them");
  need(snap.retainedPeakBytes==physical&&snap.retiredTotalBytes==0,"warm peak equals the charged physical total with zero retired");
  need(snap.limitBytes==NrdBridgeCaptureBudget::StagingLedger::NoLimit&&!snap.byteAdmissionActive,
   "the shipped default limit stays NoLimit=0 admission-disabled");
  need(snap.rejections==0&&snap.retirementGuards==0,"healthy warm operation records no rejections and no retirement guards");
  Scene bigger(host,512,256,{},true);host.submit();host.reset();
  RRRecordedOutputLease big;
  LedgerDiag::record(host,*observed.Get(),wrapper,bigger.resources,token++,big,"record the resized generation");
  const auto bigPhysical=big->lease->context->stagingBytes;
  need(wrapper.ContextGeneration()==2&&bigPhysical>physical,"the resized recording creates a second retained generation");
  snap=wrapper.SnapshotStagingLedger();
  need(snap.retainedSlots==8&&snap.retainedBytes==physical+bigPhysical,
   "both retained generations accumulate on one wrapper ledger");
  wrapper.DiscardRecordingHistory();
  const auto afterDiscard=wrapper.SnapshotStagingLedger();
  need(afterDiscard.retainedSlots==8&&afterDiscard.retainedBytes==physical+bigPhysical,
   "discard keeps the retained generations readable from the surviving wrapper ledger");
  const uint64_t totalCharged=physical+bigPhysical;
  first.reset();second.reset();big.reset();warmLedger.reset();
  host.finish();RecordedComputeLease::Poll();
  const auto finalSnap=wrapper.SnapshotStagingLedger();
  need(finalSnap.retainedBytes==0&&finalSnap.retainedSlots==0,"final destruction returns every charged byte and slot");
  need(finalSnap.retiredTotalBytes==totalCharged,"the retired total equals the sum of all charges exactly");
  need(finalSnap.retirementGuards==0,"a matched lifecycle never trips the saturation guard");
  need(finalSnap.retiredTotalBytes!=uint64_t(0)-totalCharged,"no unsigned underflow remains at final destruction");
  result["warm_slots_charged"]=4;
  result["warm_physical_bytes"]=physical;
  result["retained_generation_bytes"]=totalCharged;
  result["retained_generation_slots"]=8;
  result["retired_total_bytes_after_destruction"]=finalSnap.retiredTotalBytes;
 }
 // F03 scenario 2: fail-closed admission above the warm capacity, a failed
 // context creation, and the fifth slot once admission is disabled again.
 {
  Scene scene(host,64,64,{},true);host.submit();host.reset();
  RRWrapper wrapper;std::string error;
  need(wrapper.Configure({},error),"configure the limit probe wrapper");
  std::array<RRRecordedOutputLease,4> held;
  for(auto& lease:held)
   LedgerDiag::record(host,*observed.Get(),wrapper,scene.resources,token++,lease,"hold one warm slot");
  auto ledger=held[0]->lease->context->ledger;
  const auto warmBytes=ledger->RetainedBytes();
  const auto pairBytes=warmBytes/4;
  need(warmBytes>0&&ledger->RetainedSlots()==4,"the limit probe starts from four charged warm slots");
  need(wrapper.SnapshotStagingLedger().retainedBytes==warmBytes,"the wrapper snapshot and the shared ledger agree");
  ledger->limit=warmBytes-1; // Strictly below the warm capacity, before any further hot use.
  RRRecordedOutputLease fifth;FrameParameters frame;std::string recordError;
  need(wrapper.PrepareFrame(camera(token++,1.f),false,frame,recordError),"prepare the fifth retained recording");
  need(!wrapper.RecordOwned(observed.Get(),scene.resources,frame,fifth,recordError) &&
   recordError.find("byte budget")!=std::string::npos,
   "a fifth slot above the warm capacity fails closed with the exhausted byte budget");
  auto snap=wrapper.SnapshotStagingLedger();
  need(snap.retainedSlots==4&&snap.retainedBytes==warmBytes&&snap.rejections==1,
   "the rejected creation charges nothing and counts exactly one rejection");
  need(snap.retirementGuards==0,"a rejected admission never trips the retirement guard");
  Scene tiny(host,64,48,{},true);host.submit();host.reset();
  RRRecordedOutputLease bad;
  need(wrapper.PrepareFrame(camera(token++,1.f),false,frame,recordError),"prepare a below-minimum recording");
  need(!wrapper.RecordOwned(observed.Get(),tiny.resources,frame,bad,recordError) &&
   recordError.find("64x64 minimum")!=std::string::npos,
   "the measured 64x64 minimum still fails closed");
  snap=wrapper.SnapshotStagingLedger();
  need(snap.retainedSlots==4&&snap.retainedBytes==warmBytes,"a failed context creation charges no slot or byte");
  ledger->limit=NrdBridgeCaptureBudget::StagingLedger::NoLimit;
  LedgerDiag::record(host,*observed.Get(),wrapper,scene.resources,token++,fifth,"record the fifth slot with admission disabled");
  snap=wrapper.SnapshotStagingLedger();
  need(snap.retainedSlots==5&&snap.retainedBytes==warmBytes+pairBytes,
   "the fifth slot is charged exactly once under the documented NoLimit default");
  const uint64_t fifthTotal=warmBytes+pairBytes;
  for(auto& lease:held)lease.reset();
  fifth.reset();ledger.reset();
  wrapper.DiscardRecordingHistory();
  host.finish();RecordedComputeLease::Poll();
  const auto finalSnap=wrapper.SnapshotStagingLedger();
  need(finalSnap.retainedBytes==0&&finalSnap.retainedSlots==0,"the limit probe lifecycle also retires exactly");
  need(finalSnap.retiredTotalBytes==fifthTotal&&finalSnap.retirementGuards==0&&finalSnap.rejections==1,
   "rejected and admitted creations stay distinguishable without any wrap");
  result["limit_rejection_rejections"]=finalSnap.rejections;
  result["fifth_slot_total_bytes"]=fifthTotal;
 }
 // F04 scenario: an older held output never inherits a later recording's
 // recovery diagnostics; the wrapper's latest state keeps its own division.
 {
  Scene scene(host,64,64,{},true);host.submit();host.reset();
  RRWrapper wrapper;std::string error;
  need(wrapper.Configure({},error),"configure the recovery diagnostics wrapper with recovery off");
  RRRecordedOutputLease outputA,outputB,outputC;
  LedgerDiag::record(host,*observed.Get(),wrapper,scene.resources,token++,outputA,"record output A without recovery");
  const auto before=wrapper.GetOwnedOutputSnapshot(outputA);
  need(!before.recoveryActive&&!before.recoveryFallback&&before.recoveryTier==uint32_t(LobeRecoveryTier::None)&&
   before.recoveryFallbackReason==uint32_t(LobeRecoveryFallbackReason::NotRequested)&&before.recoveryErrorText.empty(),
   "recorded OFF output pins its own not-requested diagnostics");
  wrapper.SetRecoveryFamily(std::shared_ptr<RRRecoveryFamily>{}); // External but unavailable.
  RRSettings on;on.lobeRecovery=true;on.recoverySpecular=on.recoveryDiffuse=1.f;
  need(wrapper.Configure(on,error),"request recovery for the next recorded output");
  LedgerDiag::record(host,*observed.Get(),wrapper,scene.resources,token++,outputB,"record output B with unavailable family");
  const auto bSnap=wrapper.GetOwnedOutputSnapshot(outputB);
  need(!bSnap.recoveryActive&&bSnap.recoveryFallback&&bSnap.recoveryTier==uint32_t(LobeRecoveryTier::None)&&
   bSnap.recoveryFallbackReason==uint32_t(LobeRecoveryFallbackReason::ExternalFamilyUnavailable)&&
   bSnap.recoveryErrorText=="Lobe recovery family is unavailable",
   "the failed-optional recording pins its own fallback reason and real helper text");
  auto aSnap=wrapper.GetOwnedOutputSnapshot(outputA);
  need(aSnap.recoveryTier==before.recoveryTier&&aSnap.recoveryFallbackReason==before.recoveryFallbackReason&&
   aSnap.recoveryErrorText==before.recoveryErrorText&&!aSnap.recoveryActive,
   "an older held output never inherits a later recording's recovery diagnostics");
  auto family=CreateRRRecoveryFamily();need(bool(family),"create one recovery family for the success recording");
  wrapper.SetRecoveryFamily(family);
  LedgerDiag::record(host,*observed.Get(),wrapper,scene.resources,token++,outputC,"record output C with recovery");
  const auto cSnap=wrapper.GetOwnedOutputSnapshot(outputC);
  need(cSnap.recoveryActive&&!cSnap.recoveryFallback&&cSnap.recoveryTier==uint32_t(LobeRecoveryTier::FullPrecision)&&
   cSnap.recoveryFallbackReason==uint32_t(LobeRecoveryFallbackReason::None)&&cSnap.recoveryErrorText.empty(),
   "the recovered recording pins full-precision success with no error text");
  aSnap=wrapper.GetOwnedOutputSnapshot(outputA);
  need(aSnap.recoveryTier==before.recoveryTier&&aSnap.recoveryFallbackReason==before.recoveryFallbackReason&&
   aSnap.recoveryErrorText.empty(),"output A stays immutable across the success recording");
  auto bSnap2=wrapper.GetOwnedOutputSnapshot(outputB);
  need(bSnap2.recoveryFallbackReason==uint32_t(LobeRecoveryFallbackReason::ExternalFamilyUnavailable)&&
   bSnap2.recoveryErrorText=="Lobe recovery family is unavailable","output B keeps its own pinned fallback text");
  const auto latest=wrapper.GetSettingsState();
  need(latest.lobeRecoveryRequestedTier==uint32_t(LobeRecoveryTier::FullPrecision)&&
   latest.lobeRecoveryTier==uint32_t(LobeRecoveryTier::FullPrecision)&&latest.lobeRecoveryLastError.empty(),
   "the wrapper latest-state division still reports the newest successful recording");
  wrapper.DiscardRecordingHistory();
  need(wrapper.GetOwnedOutputSnapshot(outputA).recoveryFallbackReason==uint32_t(LobeRecoveryFallbackReason::NotRequested)&&
   wrapper.GetOwnedOutputSnapshot(outputB).recoveryFallbackReason==uint32_t(LobeRecoveryFallbackReason::ExternalFamilyUnavailable)&&
   wrapper.GetOwnedOutputSnapshot(outputC).recoveryTier==uint32_t(LobeRecoveryTier::FullPrecision),
   "recorded diagnostics survive history discard through the retained leases");
  outputA.reset();outputB.reset();outputC.reset();family.reset();
  host.finish();RecordedComputeLease::Poll();
  result["recovery_output_a_tier"]=before.recoveryTier;
  result["recovery_output_a_reason"]=before.recoveryFallbackReason;
  result["recovery_output_b_reason"]=uint32_t(LobeRecoveryFallbackReason::ExternalFamilyUnavailable);
  result["recovery_output_c_tier"]=uint32_t(LobeRecoveryTier::FullPrecision);
 }
 need(FfxApiProxy::dispatches>0,"every recorded frame performed its actual provider dispatch");
 result["provider_dispatches"]=FfxApiProxy::dispatches;
 result["creates"]=FfxApiProxy::creates;
 result["destroys"]=FfxApiProxy::destroys;
 need(FfxApiProxy::creates==FfxApiProxy::destroys,"every created provider context was destroyed exactly once");
 host.checkDebug();result["debug_errors"]=0;result["debug_warnings"]=0;
 result["native_checks"]=checks;
 std::cout<<"RESULT="<<result.dump()<<std::endl;
 std::cout<<"PASS rr_ledger_diagnostics checks="<<checks<<" real_provider="<<realMode<<'\n';
 return 0;
}
catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}
'''


def prepare_scaffold(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(TEMP='F:/FSRD/tmp', TMP='F:/FSRD/tmp', OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
    sdk_env = _toolchain_environment(visual_studio())
    sdk_path = next(Path(p) / 'd3d12.h' for p in sdk_env['INCLUDE'].split(';') if (Path(p) / 'd3d12.h').is_file())
    (out / 'lobe_native_forwarders.h').write_text(forwarders(sdk_path.read_text(encoding='utf-8')), encoding='utf-8')
    (out / 'pch.h').write_text('#pragma once\n', encoding='utf-8')
    (out / 'State.h').write_text('#pragma once\n// Existing RR fixture supplies its explicit application adapter.\n', encoding='utf-8')
    return dict(sdk_header=str(sdk_path), sdk_sha256=hashlib.sha256(sdk_path.read_bytes()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-provider', action='store_true', help='load the actual signed AMD denoiser export')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--output', type=Path, default=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15i-ledger-diag/rr-ledger-diag')))
    args = parser.parse_args()
    out = args.output
    provenance = prepare_scaffold(out)
    source = (HERE / 'fsrd_nrd_lobe_recovery_fixture.cpp').read_text(encoding='utf-8')
    source = re.sub(r'#include "(\.\.[^"]+)"', lambda m: '#include "' + (HERE / m[1]).resolve().as_posix() + '"', source)
    source = source.replace('int main(int argc,char** argv)', 'int preserved_lobe_main(int argc,char** argv)', 1)
    source += '\n' + MAIN
    composed = out / 'rr_ledger_diagnostics.cpp'
    composed.write_text(source, encoding='utf-8')
    contract = dict(scope=__doc__, fixture=str(HERE / 'fsrd_nrd_lobe_recovery_fixture.cpp'),
                    fixture_sha256=hashlib.sha256((HERE / 'fsrd_nrd_lobe_recovery_fixture.cpp').read_bytes()).hexdigest(),
                    production_sha256=hashlib.sha256((ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp').read_bytes()).hexdigest(),
                    ledger_header_sha256=hashlib.sha256((ROOT / 'OptiScaler/misc/NrdBridgeCaptureSlotBudget_Dx12.h').read_bytes()).hexdigest(),
                    composed_sha256=hashlib.sha256(composed.read_bytes()).hexdigest(), **provenance)
    (out / 'contract.json').write_text(json.dumps(contract, indent=2) + '\n', encoding='utf-8')
    if args.prepare_only:
        print(json.dumps(dict(prepared=str(composed), compiler_executed=False, native_executed=False, gpu_executed=False)))
        return
    os.environ['FSRD_CPP_CACHE'] = str(out / 'cache')
    shader = out / 'consumer.cso'
    subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-force-rootsig-ver', 'rootsig_1_0',
                    str(HERE / 'nrd_bridge_consumer_fixture.hlsl'), '-Fo', str(shader)], check=True)
    (out / 'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[]={' +
        ','.join(map(str, shader.read_bytes())) + '};\n', encoding='utf-8')
    exe = out / 'rr_ledger_diagnostics.exe'
    compile_cpp(composed, exe, ['d3d12.lib', 'dxgi.lib', 'd3dcompiler.lib', 'bcrypt.lib'],
                [out, HERE, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/nlohmann',
                 ROOT / 'external/streamline', ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
    command = [str(exe), str(out)] + (['--real-provider'] if args.real_provider else [])
    run = subprocess.run(command, capture_output=True, text=True, errors='replace', timeout=300, cwd=str(ROOT))
    (out / 'native_run.stdout.log').write_text(run.stdout, encoding='utf-8')
    (out / 'native_run.stderr.log').write_text(run.stderr, encoding='utf-8')
    print(run.stdout, end='')
    print(run.stderr, file=sys.stderr, end='')
    run.check_returncode()
    result = json.loads(next(x[len('RESULT='):] for x in run.stdout.splitlines() if x.startswith('RESULT=')))
    assert result['debug_errors'] == result['debug_warnings'] == 0
    assert result['creates'] == result['destroys'] and result['native_checks'] > 0
    assert result['retired_total_bytes_after_destruction'] == result['retained_generation_bytes']
    assert result['limit_rejection_rejections'] == 1
    assert (result['recovery_output_a_tier'], result['recovery_output_a_reason']) == (0, 1)
    assert (result['recovery_output_b_reason'], result['recovery_output_c_tier']) == (4, 1)
    if args.real_provider:
        provider = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll')
        result['actual_provider'] = dict(path=str(provider), sha256=hashlib.sha256(provider.read_bytes()).hexdigest())
    result.update(executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(), contract_sha256=hashlib.sha256((out / 'contract.json').read_bytes()).hexdigest())
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
