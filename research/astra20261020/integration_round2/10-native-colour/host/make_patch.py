"""Generate the additive integration proposal from the immutable base blobs.

Writes ONLY integration.patch and patch_manifest.json here. It never edits a
production file. The proposal requires the new source files in this delivery.
"""
from pathlib import Path
import difflib
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
BASE = '5fe436dd9a21cb9cc69dec371521a055c9af049d'
PREFIX = 'research/astra20261020/integration_round2/10-native-colour'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise AssertionError('frozen insertion point changed: '+old[:100])
    return text.replace(old,new,1)


def build():
    paths = ('OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h',
             'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp',
             'OptiScaler/OptiScaler.vcxproj')
    original = {path:subprocess.check_output(['git','show',BASE+':'+path],cwd=REPO) for path in paths}
    h,cpp,project = [original[path].decode('utf-8') for path in paths]
    h=replace_once(h,'namespace NrdBridgeStagePerf { struct Sample; }',
        'namespace NrdBridgeStagePerf { struct Sample; }\nnamespace NativeColour { struct BridgeRequest; }')
    h=replace_once(h,'    bool RecordOwned(ID3D12GraphicsCommandList*',
        '    // One-shot research request under existing injection serialization; null is default OFF.\n'
        '    // Job09 observations are not certificates; job11 must supply a real producer.\n'
        '    void SetNativeColourResearchRequest(std::shared_ptr<const NativeColour::BridgeRequest>);\n'
        '    bool RecordOwned(ID3D12GraphicsCommandList*')
    h=replace_once(h,'struct RRRecordedOutputSnapshot\n{',
        'struct RRRecordedOutputSnapshot\n{\n'
        '    bool nativeColourActive = false;\n'
        '    std::array<uint32_t,2> nativeColourDecision {1u,1u}; // D,S: Decision::Off\n')
    cpp=replace_once(cpp,'#include "FSRDNrdPostMotionAnchor_Dx12.h"',
        '#include "FSRDNrdPostMotionAnchor_Dx12.h"\n'
        '#include "../../../'+PREFIX+'/host/NativeColourBridgeRequest.h"')
    cpp=replace_once(cpp,'    NativePostMotionAnchor::Prepared inputAnchor;',
        '    NativePostMotionAnchor::Prepared inputAnchor;\n'
        '    std::array<NativeColour::NativeColourPass::Prepared,2> nativeColour; // D,S\n')
    cpp=replace_once(cpp,'    bool inputAnchorFallback = false;',
        '    bool inputAnchorFallback = false;\n'
        '    bool nativeColourActive = false;\n'
        '    std::array<uint32_t,2> nativeColourDecision {uint32_t(NativeColour::Decision::Off),\n'
        '        uint32_t(NativeColour::Decision::Off)};')
    cpp=replace_once(cpp,'    NativePostMotionAnchor inputAnchor;',
        '    NativePostMotionAnchor inputAnchor;\n'
        '    std::shared_ptr<const NativeColour::BridgeRequest> nativeColourRequest;')
    cpp=replace_once(cpp,'RRWrapper::RRWrapper() = default;',
        'RRWrapper::RRWrapper() = default;\n'
        'void RRWrapper::SetNativeColourResearchRequest(std::shared_ptr<const NativeColour::BridgeRequest> request)\n'
        '{\n'
        '    if (!impl_) impl_ = MakeOwnedShared<Impl>();\n'
        '    impl_->nativeColourRequest = std::move(request);\n'
        '}')
    # Consume before any early reject, so a failed attempt never reuses a request.
    cpp=replace_once(cpp,'    auto input = sourceInput;\n    if (!impl_) impl_ = MakeOwnedShared<Impl>();',
        '    auto input = sourceInput;\n    if (!impl_) impl_ = MakeOwnedShared<Impl>();\n'
        '    auto colourRequest = std::move(impl_->nativeColourRequest);')
    early=r'''    // Job10: prepare both optional colour lobes before provider commands and
    // before retaining the DispatchLease. No production certificate is guessed.
    using ColourPass = NativeColour::NativeColourPass;
    std::array<uint32_t,2> colourDecision {uint32_t(NativeColour::Decision::Off),
        uint32_t(NativeColour::Decision::Off)};
    if (colourRequest && colourRequest->config.enabled)
    {
        const auto failure = [&](NativeColour::Decision decision) {
            colourDecision.fill(uint32_t(decision)); lease->nativeColour = {};
        };
        try
        {
            const auto& request = *colourRequest;
            const auto identity = RecordedComputeLease::Capture(list);
            bool snapshotIsolated = true;
            for (const auto& supplied : request.lobes)
                for (auto* mutableColour : {input.spec,input.diff,lease->slot->spec.Get(),
                    lease->slot->diff.Get(),committedSpec,committedDiff})
                    if (supplied.source.resource == mutableColour) snapshotIsolated = false;
            const bool nativeRoute = impl_->settings.radianceScale.enabled &&
                uint32_t(impl_->settings.radianceScale.diffuse) == 16 &&
                uint32_t(impl_->settings.radianceScale.specular) == 256 &&
                !impl_->settings.postMotionAnchor && !impl_->settings.turnColourFilter &&
                !impl_->settings.turnBrightness && !lease->context->debugEnabled;
            if (!NativeColour::ValidConfig(request.config)) failure(NativeColour::Decision::InvalidConfig);
            else if (!request.config.acknowledgeRejectedResearch) failure(NativeColour::Decision::Off);
            else if (request.config.strength == 0 || request.config.maxLogDelta == 0)
                failure(NativeColour::Decision::ZeroStrength);
            else if (reset || recreate) failure(NativeColour::Decision::ResetOrResize);
            else if (!nativeRoute || !snapshotIsolated) failure(NativeColour::Decision::UnsupportedSource);
            else if (!identity || !identity->id || !request.convertedOwner ||
                request.streamlineFrame != frame.streamlineFrame ||
                request.convertedSpec != input.spec || request.convertedDiff != input.diff ||
                request.convertedDepth != input.linearDepth || request.convertedNormals != input.normals)
                failure(NativeColour::Decision::InvalidIdentity);
            else
            {
                if (!impl_->recoveryFamily && !impl_->externalRecoveryFamily)
                    impl_->recoveryFamily = CreateRRRecoveryFamily();
                if (!impl_->recoveryFamily) failure(NativeColour::Decision::MissingBudget);
                else
                {
                    auto& family = impl_->recoveryFamily->budget;
                    NativeColour::Budget budget {impl_->recoveryFamily,&family.graphBytes,
                        &family.retainedPeakBytes,&family.slots.allocatedSlots,
                        LobeRecovery::Family::GraphByteLimit,NrdBridgeCaptureBudget::Family::Capacity};
                    const D3D12_SHADER_BYTECODE bytecode {request.shader && !request.shader->empty() ?
                        request.shader->data() : nullptr,request.shader ? request.shader->size() : 0};
                    for (size_t lobe = 0; lobe < 2; ++lobe)
                    {
                        const auto& provided = request.lobes[lobe];
                        auto id = provided.evidence.identity;
                        if (id.frame != frame.frameIndex || id.generation != lease->context->generation ||
                            id.recording != identity->id || id.activeWidth != input.width ||
                            id.activeHeight != input.height || uint32_t(id.lobe) != lobe)
                        { colourDecision[lobe] = uint32_t(NativeColour::Decision::InvalidIdentity); break; }
                        // Identity render/crop is supplied and certified by the producer.
                        // It is never reconstructed from alpha, RGB or title dimensions.
                        auto* raw = lobe ? lease->slot->spec.Get() : lease->slot->diff.Get();
                        auto* selected = lobe ? committedSpec : committedDiff;
                        std::shared_ptr<void> selectedOwner = lease->slot;
                        if (lease->recovery.owner) selectedOwner = lease->recovery.owner;
                        if (flatPrepared) selectedOwner = lease->flatAlbedo.owner;
                        NativeColour::Inputs colour;
                        colour.frame = {id,reset,recreate}; colour.evidence = provided.evidence;
                        colour.source = provided.source;
                        colour.authority = provided.authority; colour.support = provided.support;
                        colour.rawRR = {raw,lease->slot,id,D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
                        colour.selected = {selected,selectedOwner,id,D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
                        colour.depth = {input.linearDepth,request.convertedOwner,id,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};
                        colour.normalRoughness = {input.normals,request.convertedOwner,id,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};
                        colourDecision[lobe] = uint32_t(ColourPass::Prepare(device.Get(),list,colour,
                            request.config,budget,bytecode,lease->nativeColour[lobe]));
                    }
                    // Pair atomicity: a partial prepare cannot change either selected lobe.
                    if (!lease->nativeColour[0] || !lease->nativeColour[1]) lease->nativeColour = {};
                }
            }
        }
        catch (...) { failure(NativeColour::Decision::AllocationFailed); }
    }
'''
    cpp=replace_once(cpp,'    // Allocate the public opaque owner before any provider commands can be recorded.',
        early+'    // Allocate the public opaque owner before any provider commands can be recorded.')
    cpp=replace_once(cpp,'    recorded->flatAlbedoError = impl_->flatAlbedoError;',
        '    recorded->flatAlbedoError = impl_->flatAlbedoError;\n'
        '    recorded->nativeColourDecision = colourDecision;')
    late=r'''    // Provider restoration RAII, recovery and flat selection have completed.
    // Revalidate the exact recording before either pass writes. Every owner,
    // descriptor, upload buffer and budget charge is already in DispatchLease.
    if (lease->nativeColour[0] && lease->nativeColour[1])
    {
        const auto current = RecordedComputeLease::Capture(list);
        if (current == nativeRecording && current && current->id == recorded->recordingId &&
            ColourPass::CanRecord(list,current->id,lease->nativeColour[0]) &&
            ColourPass::CanRecord(list,current->id,lease->nativeColour[1]))
        {
            const bool diffRecorded = ColourPass::Record(list,current->id,lease->nativeColour[0]);
            const bool specRecorded = ColourPass::Record(list,current->id,lease->nativeColour[1]);
            if (diffRecorded && specRecorded)
            {
                committedDiff = lease->nativeColour[0].output;
                committedSpec = lease->nativeColour[1].output;
                // Actual descriptor order is SPECULAR then DIFFUSE.
                lease->context->SetCommitInputs(*lease->slot,committedSpec,committedDiff);
                recorded->selectedSpec = committedSpec; recorded->selectedDiff = committedDiff;
                recorded->nativeColourActive = true;
            }
            else recorded->nativeColourDecision.fill(uint32_t(NativeColour::Decision::InvalidRecording));
        }
        else recorded->nativeColourDecision.fill(uint32_t(NativeColour::Decision::InvalidRecording));
    }
'''
    cpp=replace_once(cpp,'    lease->context->flatWasActive = flatPrepared;',late+'    lease->context->flatWasActive = flatPrepared;')
    cpp=replace_once(cpp,'    result.outputCommitted = output->phase.load(std::memory_order_acquire) == RRRecordedOutput::Committed;',
        '    result.outputCommitted = output->phase.load(std::memory_order_acquire) == RRRecordedOutput::Committed;\n'
        '    result.nativeColourActive = output->nativeColourActive;\n'
        '    result.nativeColourDecision = output->nativeColourDecision;')
    project=replace_once(project,'    <ClCompile Include="shaders\\fsrd_preprocess\\FSRDNrdBridgeRR_Dx12.cpp" />',
        '    <ClCompile Include="shaders\\fsrd_preprocess\\FSRDNrdBridgeRR_Dx12.cpp" />\n'
        '    <ClCompile Include="..\\research\\astra20261020\\integration_round2\\10-native-colour\\native\\NativeColourPass_Dx12.cpp">\n'
        '      <PrecompiledHeader>NotUsing</PrecompiledHeader>\n'
        '    </ClCompile>')
    outputs = dict(zip(paths,(h.encode(),cpp.encode(),project.encode())))
    diff=''
    for path in paths:
        diff+='diff --git a/'+path+' b/'+path+'\n'
        diff+=''.join(difflib.unified_diff(original[path].decode().splitlines(True),
            outputs[path].decode().splitlines(True),fromfile='a/'+path,tofile='b/'+path))
    (HERE/'integration.patch').write_text(diff,encoding='utf-8')
    manifest=dict(base_commit=BASE,applied_to_production=False,windows_build_executed=False,
        patch_sha256=hashlib.sha256(diff.encode()).hexdigest(),
        files={path:dict(base_sha256=hashlib.sha256(original[path]).hexdigest(),
                        proposed_sha256=hashlib.sha256(outputs[path]).hexdigest()) for path in paths})
    (HERE/'patch_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    build()
