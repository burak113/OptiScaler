#include "../../../upscalers/fsr31/FSRDRetryPolicy.h"
#include "../../../upscalers/fsr31/FSRDResultClassification.h"
#include "../../../upscalers/fsr31/FSRDSignalPolicy.h"
#include <array>
#include <cassert>
#include <chrono>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

using FSRD::RRResult;
#define LOG_WARN(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
#define LOG_INFO(...) ((void)0)
#define FAILED(result) ((result) < 0)
constexpr unsigned NVSDK_NGX_Result_Success = 1;
constexpr unsigned NVSDK_NGX_Result_FAIL_FeatureNotSupported = 2;
#define NVSDK_NGX_Parameter_Reset "Reset"
#define NVSDK_NGX_Parameter_Sharpness "Sharpness"
#define NVSDK_NGX_Parameter_Color "Color"
#define NVSDK_NGX_Parameter_Depth "Depth"
#define NVSDK_NGX_Parameter_MotionVectors "Motion"
#define NVSDK_NGX_Parameter_GBuffer_Normals "Normals"
#define NVSDK_NGX_Parameter_GBuffer_Roughness "Roughness"
#define NVSDK_NGX_Parameter_DiffuseAlbedo "DiffuseAlbedo"
#define NVSDK_NGX_Parameter_SpecularAlbedo "SpecularAlbedo"
#define NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance "SpecularHitDistance"
#define NVSDK_NGX_Parameter_DLSSD_SpecularRayDirectionHitDistance "SpecularRayDirectionHitDistance"
#define NVSDK_NGX_Parameter_DLSSD_DiffuseHitDistance "DiffuseHitDistance"
#define NVSDK_NGX_Parameter_DLSSD_DiffuseRayDirectionHitDistance "DiffuseRayDirectionHitDistance"
#define NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_Mask "Bias"
#define NVSDK_NGX_Parameter_GBuffer_Emissive "Emissive"
#define NVSDK_NGX_Parameter_ExposureTexture "Exposure"

struct ID3D12GraphicsCommandList {};
struct ID3D12Resource {};
struct ID3D12Device
{
    int reason = 0;
    int GetDeviceRemovedReason() const { return reason; }
};
struct NVSDK_NGX_Parameter
{
    std::map<std::string, unsigned> integers {{"Reset", 0}, {"SuperSamplingDenoising.Available", 1}};
    float sharpness = 0.25f;
    unsigned Get(const char* key, unsigned* value) const
    {
        const auto found = integers.find(key);
        if (found == integers.end()) return 0;
        *value = found->second;
        return NVSDK_NGX_Result_Success;
    }
    unsigned Get(const char*, float* value) const { *value = sharpness; return NVSDK_NGX_Result_Success; }
    void Set(const char* key, unsigned value) { integers[key] = value; }
    void Set(const char* key, int value) { integers[key] = static_cast<unsigned>(value); }
    void Set(const char*, float value) { sharpness = value; }
};
bool TryGetNGXVoidPointer(const NVSDK_NGX_Parameter&, const char*, ID3D12Resource*&) { return false; }
template <class T> struct Setting
{
    T value;
    T value_or_default() const { return value; }
};
struct Config
{
    std::optional<bool> FfxDenoiserEnabled = true;
    Setting<int> FfxDenoiserDiffuseRoute { FSRDSignals::Auto }, FfxDenoiserSpecularRoute { FSRDSignals::Auto };
    Setting<bool> FfxDenoiserDenoiseDiffuse { true }, FfxDenoiserDenoiseSpecular { true };
    Setting<bool> FfxDenoiserUnsupportedAlbedoRecovery { false }, FfxDenoiserEstimateHitDistances { false };
    Setting<float> FfxDenoiserSpecularAlbedoDemodulation { 1.0f }, FfxDenoiserDiffuseAlbedoModulation { 1.0f };
    Setting<float> FfxDenoiserAdditiveLightSplit { 0.0f };
    static Config* Instance() { static Config value; return &value; }
};
struct State
{
    std::map<unsigned, bool> changeBackend;
    static State& Instance() { static State value; return value; }
};
struct FSRDStageTimings { struct Snapshot {}; };
#include "fsrd_rr_host_runtime.inc"

// The host methods below are extracted from the production feature. Only the
// provider calls and device/parameter objects are replaced by controlled doubles.
struct NativeDenoiser
{
    unsigned calls = 0, fullCalls = 0, resetSeen = 0;
    bool succeeds = true, loseDevice = false;
    ID3D12Device* device;
    explicit NativeDenoiser(ID3D12Device* value) : device(value) {}
    bool IsInited() const { return true; }
    bool Evaluate(ID3D12GraphicsCommandList*, NVSDK_NGX_Parameter* parameters)
    {
        ++fullCalls;
        return Dispatch(parameters);
    }
    bool EvaluateInternal(ID3D12GraphicsCommandList*, NVSDK_NGX_Parameter* parameters) { return Dispatch(parameters); }
    bool Dispatch(NVSDK_NGX_Parameter* parameters)
    {
        ++calls;
        resetSeen = parameters->integers["Reset"];
        parameters->sharpness = 0.9f;
        if (loseDevice) device->reason = -1;
        return succeeds;
    }
};

struct FSRDFeatureDx12
{
    struct CapturePreprocessor
    {
        unsigned aborts = 0;
        std::string reason;
        void AbortGameTrace(const std::string& value) { ++aborts; reason = value; }
    };
    std::unique_ptr<CapturePreprocessor> FSRDConvShader = std::make_unique<CapturePreprocessor>();
    ID3D12Device device;
    ID3D12Device* Device = &device;
    FSRD::RRRetryPolicy _rrRetryPolicy;
    bool _rrFailureRecordedThisEvaluation = false, _nativeAttempted = false;
    bool _preferNativeRR = false, _nativeWasActive = false, _upscalerResetPending = false;
    bool _hasDenoiserHistory = false, throwRR = false;
    uint64_t _evaluationNumber = 0, _frameCount = 0;
    unsigned rrCalls = 0, historyInvalidations = 0;
    RRResult nextRR = RRResult::Success;
    std::string _rrFailure;
    std::mutex _runtimeMutex;
    FSRDRuntimeSnapshot _runtime, _publishedRuntime;
    FSRDRuntimeSnapshot::Step _failedStep = FSRDRuntimeSnapshot::Inputs;
    std::unique_ptr<NativeDenoiser> _nativeDenoiser = std::make_unique<NativeDenoiser>(Device);
    FSRDSignals::Plan _plan { FSRDSignals::Bit(FSRDSignals::DirectDiffuse) | FSRDSignals::Bit(FSRDSignals::DirectSpecular) };
    uint32_t _signalMask = _plan.mask, signalStatus = 0;
    bool _seenSpecularDistance = false, _seenDiffuseDistance = false, _signalsObserved = false;
    bool _preprocessorHasRecordedWork = false;
    FSRDSignals::Request _frameRequest;
    bool _frameAlbedoFixAllowed = false;
    unsigned contextCreates = 0, contextDestroys = 0;
    RRResult nextCreate = RRResult::Success;
    struct
    {
        struct
        {
            ID3D12Resource* InSpecHitDist = nullptr;
            ID3D12Resource* InSpecularRayDirectionHitDistance = nullptr;
            ID3D12Resource* InDiffuseHitDistance = nullptr;
        } Resources;
        uint32_t DiffuseHitDistanceMode = 1;
    } _convDesc;
    struct TestHandle { unsigned Id = 0; } handle;
    TestHandle* Handle() { return &handle; }
    void PublishSignalStatus()
    {
        signalStatus = FSRDSignals::Status { _signalsObserved, _seenSpecularDistance, _seenDiffuseDistance, false, _plan }.Pack();
    }
    void DestroyDenoiserContext() { ++contextDestroys; }
    RRResult CreateDenoiserContext()
    {
        ++contextCreates;
        if (nextCreate == RRResult::Success)
        {
            _plan = FSRDSignals::MakePlan(FSRDSignals::RequestFrom(*Config::Instance()), _seenSpecularDistance, _seenDiffuseDistance);
            _signalMask = _plan.mask;
            _rrRetryPolicy.Reset();
            PublishSignalStatus();
        }
        return nextCreate;
    }
    RRResult ResolveSignalTypes(bool);

    void InvalidateDenoiserHistory() { _hasDenoiserHistory = false; ++historyInvalidations; }
    RRResult EvaluateRayRegeneration(ID3D12GraphicsCommandList*, NVSDK_NGX_Parameter*)
    {
        ++rrCalls;
        if (throwRR) throw std::runtime_error("provider exception");
        if (nextRR == RRResult::Success)
        {
            using R = FSRDRuntimeSnapshot;
            for (const auto step : {R::Inputs, R::Conversion, R::RayRegeneration, R::Composition, R::SuperResolution})
                _runtime.Complete(step);
            _runtime.rrDispatched = true;
            _hasDenoiserHistory = true;
        }
        return nextRR;
    }
    bool WantsFsrRR() const;
    RRResult ClassifyRayRegenerationFailure(ffxReturnCode_t, bool) const noexcept;
    void FailRayRegeneration(RRResult, const char*);
    void RequestGameNative(NVSDK_NGX_Parameter*);
    void OnEvaluationStarting(NVSDK_NGX_Parameter*);
    bool EvaluateNative(ID3D12GraphicsCommandList*, NVSDK_NGX_Parameter*, bool);
    bool EvaluateInternal(ID3D12GraphicsCommandList*, NVSDK_NGX_Parameter*);
    bool EvaluateFallback(ID3D12GraphicsCommandList*, NVSDK_NGX_Parameter*);
    void OnEvaluationFinished(bool);

    bool Frame(bool outputSucceeds = true, bool sharedInputSucceeds = true, unsigned gameReset = 0)
    {
        ID3D12GraphicsCommandList list;
        NVSDK_NGX_Parameter parameters;
        parameters.Set(NVSDK_NGX_Parameter_Reset, gameReset);
        OnEvaluationStarting(&parameters);
        bool success = sharedInputSucceeds && EvaluateInternal(&list, &parameters) && outputSucceeds;
        if (!success) success = EvaluateFallback(&list, &parameters);
        OnEvaluationFinished(success);
        assert(parameters.integers["Reset"] == gameReset && parameters.sharpness == 0.25f);
        if (_rrRetryPolicy.Result() == RRResult::RetryableInputFailure)
            assert(parameters.integers["SuperSamplingDenoising.Available"] == 1);
        return success;
    }
};
#include "fsrd_rr_host_methods.inc"

int main()
{
    // A failed RR evaluation must close a pending capture before native fallback
    // can supply a different frame; missing preprocessors remain a valid path.
    FSRDFeatureDx12 failedCapture;
    failedCapture.FailRayRegeneration(RRResult::RetryableInputFailure, "capture frame failed");
    assert(failedCapture.FSRDConvShader->aborts == 1);
    assert(failedCapture.FSRDConvShader->reason == "capture frame failed");
    failedCapture.FSRDConvShader.reset();
    failedCapture.FailRayRegeneration(RRResult::RetryableInputFailure, "no preprocessor");

    // These methods are the real production methods, not a retry-state model.
    // Every evaluation completes through native while RR-only inputs keep
    // failing; probing RR must not interrupt the previous native history.
    FSRDFeatureDx12 continuousNative;
    continuousNative.nextRR = RRResult::RetryableInputFailure;
    std::vector<unsigned> rrAttemptFrames, nativeResetFrames;
    for (unsigned frame = 1; frame <= 129; ++frame)
    {
        const unsigned previousAttempts = continuousNative.rrCalls;
        assert(continuousNative.Frame());
        assert(continuousNative._nativeWasActive && continuousNative._runtime.nativeActive);
        if (continuousNative.rrCalls != previousAttempts) rrAttemptFrames.push_back(frame);
        if (continuousNative._nativeDenoiser->resetSeen) nativeResetFrames.push_back(frame);
    }
    std::cout << "Production native continuity, 129 evaluations: RR attempts=";
    for (const auto frame : rrAttemptFrames) std::cout << frame << ',';
    std::cout << " native resets=";
    for (const auto frame : nativeResetFrames) std::cout << frame << ',';
    std::cout << std::endl;
    assert((rrAttemptFrames == std::vector<unsigned> {1, 2, 4, 8, 16, 32, 64, 125}));
    assert((nativeResetFrames == std::vector<unsigned> {1}));
    assert(continuousNative._nativeDenoiser->calls == 129);

    // A game-requested reset is still delivered during continuous native
    // fallback, and the guard restores the game's exact parameter afterward.
    assert(continuousNative.Frame(true, true, 1));
    assert(continuousNative._nativeDenoiser->resetSeen == 1);
    assert(continuousNative.Frame(true, true, 7));
    assert(continuousNative._nativeDenoiser->resetSeen == 7);
    assert(continuousNative.Frame());
    assert(continuousNative._nativeDenoiser->resetSeen == 0);

    // Selecting native after a completed FSR-RR/SR frame is a real history gap.
    // Staying on the requested native path must then preserve continuity.
    FSRDFeatureDx12 pathTransition;
    Config::Instance()->FfxDenoiserEnabled = false;
    assert(pathTransition.Frame() && pathTransition._nativeDenoiser->resetSeen == 1);
    assert(pathTransition.Frame() && pathTransition._nativeDenoiser->resetSeen == 0);
    Config::Instance()->FfxDenoiserEnabled = true;
    assert(pathTransition.Frame() && pathTransition._runtime.rrValidated && !pathTransition._nativeWasActive);
    Config::Instance()->FfxDenoiserEnabled = false;
    assert(pathTransition.Frame() && pathTransition._nativeDenoiser->resetSeen == 1);
    assert(pathTransition.Frame() && pathTransition._nativeDenoiser->resetSeen == 0);

    // A native dispatch cannot establish continuity if final output fails.
    assert(!pathTransition.Frame(false) && !pathTransition._nativeWasActive);
    assert(pathTransition.Frame() && pathTransition._nativeDenoiser->resetSeen == 1);
    assert(pathTransition.Frame() && pathTransition._nativeDenoiser->resetSeen == 0);

    // Failed native dispatch also creates a genuine gap, even though it ran.
    pathTransition._nativeDenoiser->succeeds = false;
    assert(!pathTransition.Frame() && !pathTransition._nativeWasActive);
    pathTransition._nativeDenoiser->succeeds = true;
    assert(pathTransition.Frame() && pathTransition._nativeDenoiser->resetSeen == 1);
    assert(pathTransition.Frame() && pathTransition._nativeDenoiser->resetSeen == 0);

    // Native context recreation creates a new feature instance; history state
    // must start false, independently of a still-active prior instance.
    FSRDFeatureDx12 recreatedNative;
    assert(!recreatedNative._nativeWasActive && pathTransition._nativeWasActive);
    assert(recreatedNative.Frame() && recreatedNative._nativeDenoiser->resetSeen == 1);
    assert(recreatedNative.Frame() && recreatedNative._nativeDenoiser->resetSeen == 0);
    Config::Instance()->FfxDenoiserEnabled = true;

    FSRDFeatureDx12 transient;
    transient.nextRR = RRResult::RetryableInputFailure;
    assert(transient.Frame()); // Native fallback safely completes the rejected frame.
    assert(transient._rrRetryPolicy.Result() == RRResult::RetryableInputFailure);
    assert(transient._nativeDenoiser->calls == 1 && transient._nativeDenoiser->fullCalls == 1);
    assert(transient._nativeDenoiser->resetSeen == 1 && !transient._runtime.rrValidated);
    transient.nextRR = RRResult::Success;
    assert(transient.Frame() && transient.rrCalls == 2);
    assert(transient._rrRetryPolicy.Result() == RRResult::Success && transient._runtime.rrValidated);
    assert(transient._runtime.failure.empty() && transient._hasDenoiserHistory);

    FSRDFeatureDx12 repeated;
    repeated.nextRR = RRResult::RetryableInputFailure;
    assert(repeated.Frame() && repeated.Frame());
    assert(repeated._rrRetryPolicy.SkippedFramesRemaining() == 1);
    assert(repeated.Frame() && repeated.rrCalls == 2);
    assert(repeated._rrRetryPolicy.SkippedFramesRemaining() == 0); // No double counting on fallback.
    for (unsigned frame = 0; frame != 500; ++frame)
    {
        assert(repeated.Frame());
        assert(repeated._rrRetryPolicy.Result() == RRResult::RetryableInputFailure);
        assert(repeated._rrRetryPolicy.SkippedFramesRemaining() <= 60);
    }
    assert(repeated.rrCalls < 20 && repeated._nativeDenoiser->calls == 503);
    repeated.nextRR = RRResult::Success;
    for (unsigned frame = 0; frame <= 60 && !repeated._runtime.rrValidated; ++frame) assert(repeated.Frame());
    assert(repeated._runtime.rrValidated && repeated._rrRetryPolicy.Result() == RRResult::Success);

    FSRDFeatureDx12 noNative;
    noNative._nativeDenoiser.reset();
    noNative.nextRR = RRResult::RetryableInputFailure;
    assert(!noNative.Frame() && !noNative._runtime.gameNativeRequested);
    noNative.nextRR = RRResult::Success;
    assert(noNative.Frame() && noNative._runtime.rrValidated);

    for (const auto fault : {RRResult::NeedsRecreation, RRResult::UnsupportedProvider})
    {
        FSRDFeatureDx12 permanent;
        permanent.nextRR = fault;
        for (unsigned frame = 0; frame != 5; ++frame) assert(permanent.Frame());
        assert(permanent.rrCalls == 1 && permanent._rrRetryPolicy.Result() == fault);
        assert(!permanent._runtime.rrValidated && !permanent._rrFailure.empty());
        permanent._nativeDenoiser.reset();
        assert(!permanent.Frame() && permanent._runtime.gameNativeRequested);
    }

    FSRDFeatureDx12 lost;
    lost.device.reason = -1;
    assert(!lost.Frame() && lost.rrCalls == 0 && lost._nativeDenoiser->calls == 0);
    assert(lost._rrRetryPolicy.Result() == RRResult::DeviceLost);
    lost.device.reason = 0;
    assert(!lost.Frame() && lost.rrCalls == 0 && lost._nativeDenoiser->calls == 0);

    FSRDFeatureDx12 lostInNative;
    lostInNative.nextRR = RRResult::RetryableInputFailure;
    lostInNative._nativeDenoiser->loseDevice = true;
    assert(!lostInNative.Frame() && lostInNative._rrRetryPolicy.Result() == RRResult::DeviceLost);

    FSRDFeatureDx12 output;
    assert(output.Frame(false));
    assert(output._rrRetryPolicy.Result() == RRResult::NeedsRecreation && !output._runtime.rrValidated);
    assert(output._runtime.steps[FSRDRuntimeSnapshot::Output] == FSRDRuntimeSnapshot::Failed);

    FSRDFeatureDx12 input;
    assert(input.Frame(true, false));
    assert(input.rrCalls == 0 && input._rrRetryPolicy.Result() == RRResult::RetryableInputFailure);
    assert(input.Frame() && input._runtime.rrValidated);

    FSRDFeatureDx12 exception;
    exception.throwRR = true;
    assert(exception.Frame() && exception._rrRetryPolicy.Result() == RRResult::NeedsRecreation);

    ID3D12Resource guide;
    FSRDFeatureDx12 signals;
    signals._convDesc.Resources.InSpecHitDist = &guide;
    assert(signals.ResolveSignalTypes(true) == RRResult::Success && signals.contextCreates == 1);
    signals._preprocessorHasRecordedWork = true;
    signals._convDesc.Resources.InSpecHitDist = nullptr;
    assert(signals.ResolveSignalTypes(true) == RRResult::RetryableInputFailure);
    assert(signals.contextCreates == 1 && signals.contextDestroys == 1 && !State::Instance().changeBackend[0]);
    signals._convDesc.Resources.InSpecHitDist = &guide;
    assert(signals.ResolveSignalTypes(true) == RRResult::Success && signals.contextCreates == 1);
    signals._convDesc.Resources.InDiffuseHitDistance = &guide;
    assert(signals.ResolveSignalTypes(true) == RRResult::NeedsRecreation);
    assert(State::Instance().changeBackend[0] && signals.contextCreates == 1 && signals.contextDestroys == 1);

    // Changing routing to Direct must release the dependency on the old missing
    // guide through a deliberate rebuild, rather than waiting for it forever.
    State::Instance().changeBackend[0] = false;
    signals._convDesc.Resources.InSpecHitDist = nullptr;
    signals._convDesc.Resources.InDiffuseHitDistance = nullptr;
    Config::Instance()->FfxDenoiserSpecularRoute.value = FSRDSignals::Direct;
    assert(signals.ResolveSignalTypes(true) == RRResult::NeedsRecreation);
    assert(State::Instance().changeBackend[0]);
    Config::Instance()->FfxDenoiserSpecularRoute.value = FSRDSignals::Auto;

    State::Instance().changeBackend[0] = false;
    FSRDFeatureDx12 rejectedPlan;
    rejectedPlan._convDesc.Resources.InSpecHitDist = &guide;
    rejectedPlan.nextCreate = RRResult::UnsupportedProvider;
    assert(rejectedPlan.ResolveSignalTypes(true) == RRResult::UnsupportedProvider);
    assert(rejectedPlan.contextCreates == 1 && !State::Instance().changeBackend[0]);
    rejectedPlan.FailRayRegeneration(RRResult::UnsupportedProvider, "new plan rejected");
    assert(rejectedPlan.Frame() && rejectedPlan.rrCalls == 0 && rejectedPlan.contextCreates == 1);

    FSRDFeatureDx12 invalidInput;
    invalidInput._convDesc.Resources.InSpecHitDist = &guide;
    assert(invalidInput.ResolveSignalTypes(false) == RRResult::RetryableInputFailure);
    assert(!invalidInput._seenSpecularDistance && invalidInput.contextCreates == 0);
    // The albedo fix plans all four signals with only a specular guide: its Indirect
    // Diffuse slot carries the unmodulated copy, whose ray length falls back to view
    // depth. Every combination must keep resolving after work has been recorded, and a
    // live pause must only ask for a diffuse guide when the paused slot splits the lobe.
    auto& cfg = *Config::Instance();
    for (int combo = 0; combo < 8; ++combo)
    {
        const bool fix = combo & 1, estimate = combo & 2, diffuseGuide = combo & 4;
        cfg.FfxDenoiserUnsupportedAlbedoRecovery.value = fix;
        cfg.FfxDenoiserEstimateHitDistances.value = estimate;
        FSRDFeatureDx12 planned;
        planned._convDesc.Resources.InSpecHitDist = &guide;
        planned._convDesc.Resources.InDiffuseHitDistance = diffuseGuide ? &guide : nullptr;
        planned._seenSpecularDistance = true;
        planned._seenDiffuseDistance = diffuseGuide;
        planned.CreateDenoiserContext();
        assert(planned._plan.albedoFix == fix);
        for (const bool recorded : {false, true})
        {
            planned._preprocessorHasRecordedWork = recorded;
            for (int frame = 0; frame < 128; ++frame)
                assert(planned.ResolveSignalTypes(true) == RRResult::Success);
        }
        // Pause the fix live (changed modulation), then re-enable it.
        cfg.FfxDenoiserDiffuseAlbedoModulation.value = 0.5f;
        const auto paused = FSRDSignals::FixDiffuseRole(planned._plan, false, diffuseGuide || estimate);
        assert(planned.ResolveSignalTypes(true) == RRResult::Success);
        assert(!fix || paused == (diffuseGuide || estimate ? FSRDSignals::FixDiffuse::Split
                                                           : FSRDSignals::FixDiffuse::Empty));
        // A split half loses its guide for a frame: retry, as any routed Indirect would.
        planned._convDesc.Resources.InDiffuseHitDistance = nullptr;
        const bool guideLost = diffuseGuide && !estimate;
        assert(planned.ResolveSignalTypes(true) ==
               (guideLost ? RRResult::RetryableInputFailure : RRResult::Success));
        // The live fix's copy needs no title ray length.
        cfg.FfxDenoiserDiffuseAlbedoModulation.value = 1.0f;
        assert(planned.ResolveSignalTypes(true) ==
               (guideLost && !fix ? RRResult::RetryableInputFailure : RRResult::Success));
        assert(planned.contextCreates == 1 && !State::Instance().changeBackend[0]);
    }
    cfg.FfxDenoiserUnsupportedAlbedoRecovery.value = false;
    cfg.FfxDenoiserEstimateHitDistances.value = false;
    std::cout << "Production signal recovery: albedo fix with and without a diffuse guide, live pause/resume passed\n";

    std::cout << "Production signal recovery: guide dropout, plan upgrades, safe recreation and provider rejection passed\n";
    std::cout << "Production RR host recovery: transient/native fallback, cooldown accounting, output faults, and device loss passed\n";
}
