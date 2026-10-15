"""CPU source contracts only; native GPU behavior is covered by the separate owned-output fixture."""
from __future__ import annotations

import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1] / "fsrd_preprocess"
CPP = (ROOT / "FSRDNrdBridgeRR_Dx12.cpp").read_text(encoding="utf-8")
HEADER = (ROOT / "FSRDNrdBridgeRR_Dx12.h").read_text(encoding="utf-8")
checks = 0


def need(value: bool, message: str) -> None:
    global checks
    checks += 1
    if not value:
        raise AssertionError(message)


# Mask comments/literals, retaining positions, so braces in diagnostic strings cannot alter a function boundary.
def masked(text: str) -> str:
    tokens = r'//[^\r\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    return re.sub(tokens, lambda m: "".join("\n" if c == "\n" else " " for c in m.group()), text, flags=re.S)


MASKED = masked(CPP)


def body(name: str) -> str:
    start = MASKED.index(name + "(")
    opening = MASKED.index("{", start)
    level = 1
    end = opening + 1
    while level:
        level += (MASKED[end] == "{") - (MASKED[end] == "}")
        end += 1
    return CPP[opening + 1:end - 1]


def ordered(text: str, *terms: str) -> bool:
    indices = [text.index(term) for term in terms]
    return indices == sorted(indices) and len(set(indices)) == len(indices)


def main() -> None:
    record_public = body("RRWrapper::RecordOwned")
    record = body("RRWrapper::RecordOwnedImpl")
    commit = body("RRWrapper::CommitOwned")
    abandon = body("RRWrapper::AbandonOwned")
    snapshot = body("RRWrapper::GetOwnedOutputSnapshot")
    attestation = body("RRWrapper::GetOwnedOutputProviderAttestation")
    dispatch = body("RRWrapper::Dispatch")
    need("std::shared_ptr<const RRRecordedOutput>" in HEADER, "public output lease must remain opaque and const")
    for method in ("RecordOwned", "CommitOwned", "AbandonOwned", "GetOwnedOutputSnapshot", "GetOwnedOutputProviderAttestation"):
        need(method in HEADER, f"missing agreed API {method}")
    record_signature = CPP[CPP.index("bool RRWrapper::RecordOwned("):CPP.index("{", CPP.index("bool RRWrapper::RecordOwned("))]
    for forbidden in ("outputSpec", "outputDiff", "TitleSignalConstants"):
        need(forbidden not in record_signature, f"early record signature depends on title {forbidden}")
    for forbidden in ("frame.outputConstants", "frame.outputEncoding", "ValidateTitleSignalConstants", "SetCommitOutputs", "->Commit("):
        need(forbidden not in record, f"early provider recording consults title output state: {forbidden}")
    need("AcquireOwnedSlot(error)" in record, "early recording must acquire only owned stages")
    need("RecordOwnedImpl(list,input,frame,output,error,profiling,true)" in record_public,
         "public deferred path must require native commit prewarming")
    need(ordered(record, "if (prepareNativeCommit", "PrepareTableFlags(error,303)", "PrepareTableFlags(error,36)", "RetainComputeDispatch", "D3D12_Dispatch"),
         "both native profiles and owned flags must exist before provider work/suppression")
    need(ordered(record, "lease->inputs[i] = inputs[i]", "MakeOwnedShared<RRRecordedOutput>", "RetainComputeDispatch", "RecordedComputeLease::Capture(list)", "D3D12_Dispatch", "output = std::move(recorded)"),
         "owned input/context/slot and native recording lease must precede provider and publication")
    need("!nativeRecording || !nativeRecording->id" in record, "early recording must require nonzero native recording identity")
    need("std::weak_ptr<RecordedComputeLease::Recording> nativeRecording" in CPP, "opaque owner must not cycle back to native recording registry")
    for signal in ("FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE", "FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR", "FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO"):
        need(signal in record, f"actual RR mode changed: {signal}")
    need("diffuse.header.pNext = &specular.header" in record, "SDK signal chain must keep ascending DD then IS")
    need(record.count("D3D12_Dispatch(") == 1, "one actual provider call per record, no retry or alternate denoiser")
    need(ordered(record, "result != FFX_API_RETURN_OK", "lease->context->recovery->Record", "impl_->previous = frame", "++impl_->nextFrame", "output = std::move(recorded)"),
         "history/opaque publication only after successful provider work")
    need("catch (...) { AbandonOwned(recorded); throw; }" in record and "AbandonOwned(recorded); return Fail" in record,
         "provider error and exception must retire their recorded generation")
    need(record.count("++impl_->nextFrame") == 1 and "++impl_->nextFrame" not in commit,
         "SDK CPU history advances once at RecordOwned, never at late commit")
    need("impl_->previous =" not in commit, "late old commit must not overwrite newer camera history")
    need("impl_->previous.outputConstants = {}" in record, "private history must not retain borrowed Consumer CBV POD")
    need("impl_->context != lease->context" in commit and "lease->context->generation != output->contextGeneration" in commit,
         "late commit must match exact physical context generation")
    for proof in ("list != output->source", "frame.frameIndex != output->frameIndex", "frame.streamlineFrame != output->frameSL",
                  "output->nativeRecording.lock()", "RecordedComputeLease::Capture(list)", "currentRecording != originalRecording",
                  "!output->recordingId", "currentRecording->id != output->recordingId", "RecordedComputeLease::Available()"):
        need(proof in commit, f"late commit missing exact-source proof {proof}")
    need("compare_exchange_strong(expected,RRRecordedOutput::Preparing" in commit, "owned output must be single-use")
    need("~Claim() { if (!committed) wrapper->AbandonOwned(*output); }" in commit, "all late preparation failures must abandon outside admission")
    need(ordered(commit, "ValidateCommitTarget(", "TableFlagsReady(*lease->slot,frame.outputConstants.wordIndex)", "SetCommitOutputs(", "guard.admit &&"),
         "target/readiness/descriptor preparation must precede final title admission")
    deferred = commit[commit.index("if (output->nativeCommitPrepared)"):commit.index("else if (!lease->context->PrepareTableFlags") ]
    need("Initialize(" not in deferred and "PrepareTableFlags(" not in deferred,
         "deferred native late branch may validate readiness but cannot allocate capture objects")
    need("0.0f,action.selectedSpec,action.selectedDiff" in commit, "late output is selected owned RR, with native coefficient hard-off")
    action = commit[commit.index("const auto record ="):commit.index("if (guard.admit &&")]
    for forbidden in ("MakeOwnedShared", "CreateDescriptor", "CreateCommittedResource", "D3D12_Dispatch", "RetainComputeDispatch", "std::scoped_lock", "std::lock_guard"):
        need(forbidden not in action, f"guarded output action contains fallible SDK/allocation/lock work {forbidden}")
    need(ordered(action, "action.context->Commit(", "nativeEncodingCaptured", "phase.store(RRRecordedOutput::Committed"),
         "owned native flag publication must follow actual guarded capture/commit recording")
    need("impl_->context == context && context->generation == output->contextGeneration" in abandon,
         "abandonment must never retire another/newer physical generation")
    need(ordered(abandon, "output->wrapper.lock()", "phase.store(RRRecordedOutput::Abandoned", "impl_->context == context", "DiscardRecordingHistory()"),
         "abandon checks wrapper and exact generation before context retirement")
    need("output->phase" in snapshot and "result.owner = lease" in snapshot, "trace accessor must retain only bridge-owned dispatch lease")
    for field in ("rawSpec", "rawDiff", "selectedSpec", "selectedDiff", "frameSL", "frameIndex", "contextGeneration", "recordingId", "providerControl"):
        need("result." + field in snapshot, f"trace snapshot missing frozen {field}")
    need("result.outputCommitted && output->nativeEncodingCaptured" in snapshot,
         "native execution flag cannot be exposed from an uncommitted/stale slot")
    need("result.encodingFlag = lease->slot->flag.resource.Get()" in snapshot and "encodingFlagState = D3D12_RESOURCE_STATE_COMMON" in HEADER,
         "trace must receive owned balanced-COMMON encoding snapshot, not title CBV")
    need("std::array<uint8_t, 184> providerControl" in HEADER and "motionVectorScale) == 264u" in CPP,
         "trace controls must remain exact actual ABI448 tail184 at264")
    need("std::memcpy(recorded->providerControl.data()" in record, "actual provider controls must be frozen, not reconstructed")
    need("OwnedProviderAttestation<FfxApiProxy>(output->lease->context->handle)" in attestation,
         "cold trace attestation must use the retained actual provider context")
    for hot in (record, commit, snapshot):
        need("OwnedProviderAttestation" not in hot and "DenoiserRouteAttestationDx12" not in hot,
             "cold provider file hashing must never enter ordinary RR/commit/snapshot path")
    need(ordered(dispatch, "ValidateCommitTarget(", "RecordOwnedImpl(", "CommitOwned("),
         "compatibility Dispatch must validate legacy target before composing record and commit")
    need("RecordOwnedImpl(list,input,frame,output,error,profiling,false)" in dispatch,
         "legacy standalone Dispatch must retain optional capture allocation behavior")
    need("Caller holds injection serialization, outside coordinator gMutex" in HEADER,
         "abandonment serialization/lock boundary must be explicit")
    need("FSRDNrdBridgePureCommit_cso" in CPP and "FSRDNrdBridgeCommit_cso" not in CPP,
         "production wrapper must not load forbidden native RGB hybrid shader")
    need("nativeConstants ? 1u : 0u, 0u}" in CPP, "private Commit legacy root word must remain literal zero")
    print("PASS source_checks=" + str(checks))
    print(json.dumps({"source_checks": checks, "native_gpu_run": False, "compiler_run": False,
                      "scope": "source contracts only; numerical/lifetime GPU behavior not measured by this script"}))


if __name__ == "__main__":
    main()
