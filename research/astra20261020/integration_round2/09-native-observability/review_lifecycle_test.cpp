// CPU-only adversarial lifetime checks of the production RRTrace state machine.
// This does not instantiate D3D12 resources, execute a GPU, or prove host routing.
#include "OptiScaler/shaders/fsrd_preprocess/RRTraceFenceState.h"
#include <cstdint>
#include <iostream>
#include <string_view>

namespace
{
unsigned checks = 0;
bool Require(bool predicate, const char* description)
{
    ++checks;
    if (!predicate) std::cerr << "ASSERTION FAILED: " << description << '\n';
    return predicate;
}
}

int main(int argc, char** argv)
{
    using RRTraceFence::State;
    const bool broken = argc == 2 && std::string_view(argv[1]) == "--broken-release";
    auto canRelease = [broken](const State& state, std::uint64_t completed) {
        // Deliberately wrong: a completed old submission can be executed again.
        return broken ? completed >= state.expected : state.CanRelease(completed);
    };
    bool ok = true;
    State adopted;
    adopted.recorded = true;
    ok &= Require(!adopted.CanSnapshot(0), "unsubmitted observation cannot publish");
    ok &= Require(adopted.Submit(), "first actual submission is admitted");
    ok &= Require(!adopted.CanSnapshot(1), "pending signal is not completion proof");
    adopted.SignalEnqueued(true);
    ok &= Require(!adopted.CanSnapshot(0), "incomplete fence cannot publish");
    ok &= Require(adopted.CanSnapshot(1), "completed copy can freeze under submission gate");
    ok &= Require(!canRelease(adopted, 1), "completed but executable command list cannot release readback");
    adopted.ResetSucceeded();
    ok &= Require(canRelease(adopted, 1), "successful reset and completion release readback");
    ok &= Require(!adopted.Submit(), "detached old recording cannot submit again");

    // Early input copy was recorded, but RR/late commit failed before Seal.
    // It remains an unpublished orphan until an actual reset proves disposal.
    State orphan;
    ok &= Require(orphan.Submit(), "orphan may still be submitted by its native caller");
    orphan.SignalEnqueued(true);
    ok &= Require(!orphan.CanSnapshot(1), "unsealed early frame cannot publish despite completion");
    ok &= Require(!canRelease(orphan, 1), "unsealed but executable early frame cannot release");
    orphan.ResetSucceeded();
    ok &= Require(canRelease(orphan, 1), "completed orphan is released only after reset");

    State discarded;
    discarded.ResetSucceeded();
    ok &= Require(!discarded.CanSnapshot(0), "reset before submission invalidates unpublished input");
    ok &= Require(discarded.CanRelease(0), "never-submitted discarded work is releasable");

    State repeated;
    repeated.recorded = true;
    repeated.Submit(); repeated.SignalEnqueued(true);
    repeated.Submit(); repeated.SignalEnqueued(true);
    repeated.ResetSucceeded();
    ok &= Require(!repeated.CanSnapshot(2), "repeated submission cannot publish a single-pass observation");
    ok &= Require(!canRelease(repeated, 2), "ambiguous repeated submission must remain retained");

    State failed;
    failed.recorded = true;
    failed.Submit(); failed.SignalEnqueued(false); failed.ResetSucceeded();
    ok &= Require(!failed.CanSnapshot(UINT64_MAX), "failed queue signal does not prove a snapshot");
    ok &= Require(!canRelease(failed, UINT64_MAX), "failed signal cannot prove readback release");

    State removed;
    removed.recorded = true;
    removed.Submit(); removed.SignalEnqueued(true); removed.ResetSucceeded();
    ok &= Require(!removed.CanSnapshot(UINT64_MAX), "device-removal fence sentinel cannot publish");
    ok &= Require(!canRelease(removed, UINT64_MAX), "device-removal sentinel cannot prove release");

    State untracked;
    untracked.recorded = true;
    untracked.UntrackedSubmission(); untracked.ResetSucceeded();
    ok &= Require(!untracked.CanSnapshot(9), "unknown submission invalidates chronological evidence");
    ok &= Require(!canRelease(untracked, 9), "unknown submission is not a safe release proof");

    std::cout << "lifetime_checks=" << checks << " result=" << (ok ? "PASS" : "FAIL")
              << " mode=" << (broken ? "deliberately-broken-release" : "production-state") << '\n';
    return ok ? 0 : 1;
}
