// Reproduces a runtime-disabled native profile while the gameplay profiler still
// needs Consumer frames. Uses the existing actual-host fixture's explicit native
// role/Release-coverage adapters; original title shaders and submission are real.
namespace RuntimeOffFixture
{
unsigned reports = 0;
NrdBridgePerf::Report report {};

void CheckDisabled()
{
    const auto status = NrdBridge::GetStatus();
    need(!NrdBridge::RuntimeEnabled() && !status.runtimeEnabled && !status.active,
         "runtime OFF remains disabled while profiling Consumers");
    need(!status.nativeHistoryDirty && status.nativeDispatchesSkipped == 0 && status.framesBridged == 0,
         "runtime OFF never omits native work or owns RR output");
    need(RecordedComputeLease::RequiredSubmissionFailure() == S_OK && RecordedComputeLease::Available(),
         "runtime OFF cannot poison mandatory submission/completion state");
    need(FfxApiProxy::dispatches == 0 && FfxApiProxy::creates == 0,
         "runtime OFF records no provider work and allocates no RR contexts");
    need(NrdBridge::gDispatchCandidate == nullptr && !NrdBridge::gNativeTransactions.load(),
         "runtime OFF cannot nominate a dispatch for native omission");
}

// P01/P03: the startup-hook-installed but RR-disabled run ("B") still measures
// the CPU Consumer cadence. These assertions pin the new naming split so the
// thread-time sums and the per-interval cadence quantiles are actually measured
// in an integrated run, never inferred from a sum of per-hook p95 values.
void CheckPerfReport()
{
    const auto& value = report;
    need(value.ConsumerTimeValid() && value.consumerIntervalTicks > 0,
         "runtime OFF still freezes the actual 100-interval Consumer cadence span");
    size_t sampled = 0;
    for (const auto ticks : value.intervalTicks) sampled += ticks != 0;
    need(sampled == 100, "all 100 complete Consumer intervals retain their own per-interval sample");
    need(value.ConsumerIntervalP50Ms() <= value.ConsumerIntervalP95Ms() &&
         value.ConsumerIntervalP95Ms() <= value.ConsumerIntervalP99Ms() &&
         value.ConsumerIntervalP99Ms() > 0.0,
         "per-interval cadence quantiles are ordered and genuinely measured");
    need(value.ThreadTimeSumMsPerInterval() == value.SumMsPerFrame() &&
         value.ThreadTimeSumMsPerInterval(true) == value.SumMsPerFrame(true),
         "thread-time accessors expose the identical measured hook sums");
}
}

int main(int argc, char** argv) try
{
    need(argc == 4, "scratch output, signed provider and isolated runtime-OFF case");
    const std::string mode = argv[3];
    const bool startup = mode == "startup-root" || mode == "startup-table";
    const bool table = mode == "startup-table" || mode == "toggle-table";
    need(startup || mode == "toggle-root" || mode == "toggle-table", "bounded runtime-OFF test case");
    NativeFixture::Bootstrap();
    Host h;
    NativeFixtureRegister(h.device.Get()); NativeFixtureRegister(h.list.Get());
    g_dllPath = std::filesystem::path(argv[1]) / "fixture.dll";
    Config::Instance()->FfxDenoiserNrdBridge.value = true;
    Config::Instance()->FfxDenoiserNrdBridgeEnabled.value = !startup;
    NrdBridge::ConfigureStartup(true);
    loadProvider(argv[2]);
    FrameSurvey::BeginCreationTracking(false);
    need(FrameSurvey::Install(h.device.Get(), h.list.Get(), false), "actual native metadata registry installed");
    NrdBridgePerf::Configure([](const NrdBridgePerf::Report& value) noexcept {
        ++RuntimeOffFixture::reports; RuntimeOffFixture::report = value;
    });
    need(NrdBridge::Initialize(h.device.Get()), "actual production coordinator initialized");
    AttachRoots(h.list.Get()); Wiring::Attach(h.list.Get()); NativeDraw::Attach(h.list.Get());
    NrdBridge::SetNativeElisionContractForTesting(true);
    struct Hooks
    {
        ~Hooks() { NativeDraw::Detach(); Wiring::Detach(); DetachRoots(); FrameSurvey::Shutdown(); }
    } hooks;
    struct DebugCleanup { ~DebugCleanup() { emitDebug = {}; } } debugCleanup;
    {
        NativeFixture::NativeTitle title(h, table);
        struct Cleanup
        {
            Host& h;
            ~Cleanup() {
                h.waitComplete(); NrdBridge::Shutdown();
                RecordedComputeLease::Detach(RecordedComputeLease::Capture(h.list.Get()));
                RecordedComputeLease::Poll();
            }
        } cleanup {h};
        if (!startup) NrdBridge::SetRuntimeEnabled(false);
        RuntimeOffFixture::CheckDisabled();
        need(NrdBridgePerf::NeedsConsumerFrames(), "runtime-OFF reproduction starts with the Consumer sampler armed");
        for (UINT frame = 1; frame <= 101; ++frame)
        {
            title.SetWords();
            title.frame(frame, 3, 2, false);
            RuntimeOffFixture::CheckDisabled();
            const auto captured = title.capture(3, 2, false);
            need(NativeFixture::Execute(h), "runtime OFF forwards every original native title submission");
            need(title.sentinel(title.validate(captured)), "original native shaders execute once with exact original root bindings");
            h.reset();
        }
        // A disable can win gInjectionMutex after BeforeDispatch chose its action.
        // Exercise that stale action directly: it must recheck OFF before metadata
        // validation, with the intentionally closed binding window left intact.
        NrdBridge::BeginNativeTransaction(NrdBridge::gService, h.list.Get(), 0);
        NrdBridge::BeginNativeTransaction(NrdBridge::gService, h.list.Get(), 1);
        RuntimeOffFixture::CheckDisabled();
        need(NrdBridge::gService->failures == 0 && NrdBridge::gService->frame == 0,
             "runtime OFF performs no raw transaction validation or failure accounting");
        need(RuntimeOffFixture::reports == 1 && RuntimeOffFixture::report.frames == 100 &&
             RuntimeOffFixture::report.firstFrame == 1 && RuntimeOffFixture::report.lastFrame == 100 &&
             !NrdBridgePerf::NeedsConsumerFrames(), "only identified Consumers finish the single 100-interval gameplay report");
        RuntimeOffFixture::CheckPerfReport();
        need(h.denied == 0 && h.tick == 101, "all 101 actual native GPU submissions finish without a denial");
    }
    const auto debug = h.debugCounts();
    J result {{"mode", mode}, {"native_checks", checks}, {"native_submissions", h.tick},
              {"debug_errors", debug[0]}, {"debug_warnings", debug[1]},
              {"provider_dispatches", FfxApiProxy::dispatches}, {"contexts", FfxApiProxy::creates},
              {"denied_submissions", h.denied}, {"perf_reports", RuntimeOffFixture::reports},
              {"perf_frames", RuntimeOffFixture::report.frames}, {"stale_actions_checked", 2},
              {"scope", "actual coordinator/native GPU forwarding/submission with runtime OFF; synthetic shipping-role and caller-strong Release-coverage adapters; no game FPS claim"}};
    std::ofstream(std::filesystem::path(argv[1]) / "runtime-off-result.json") << result.dump(2) << '\n';
    std::cout << "PASS runtime_off " << checks << '\n';
    return 0;
}
catch (const std::exception& error)
{
    std::cerr << "FAIL runtime_off: " << error.what() << '\n';
    return 1;
}
