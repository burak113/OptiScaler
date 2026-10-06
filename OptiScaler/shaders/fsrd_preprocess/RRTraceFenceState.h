#pragma once
#include <cstdint>
// Portable state machine shared by the actual queue hook and CPU tests.
// It does not pretend that an upload/readback token is a CPU/GPU fence.
namespace RRTraceFence
{
struct State
{
    bool recorded = false;
    bool submitted = false;
    bool detached = false;
    bool invalid = false;
    bool abandoned = false;
    bool signalFailed = false;
    bool ambiguousSubmission = false;
    unsigned pendingSignals = 0;
    std::uint64_t expected = 0;

    bool Submit()
    {
        if (detached) return false;
        if (submitted)
        {
            invalid = true;
            ambiguousSubmission = true; // Never recycle uncertain repeated submissions.
        }
        submitted = true;
        ++expected;
        ++pendingSignals;
        return true;
    }
    void SignalEnqueued(bool success)
    {
        if (pendingSignals) --pendingSignals;
        else invalid = true;
        if (!success) signalFailed = true;
    }
    void ResetSucceeded()
    {
        if (!submitted) invalid = true; // Recorded commands were discarded.
        detached = true;
    }
    // Wait for Reset as well as the fence: a still-executable command list
    // could otherwise overwrite the capture during CPU export by being resubmitted.
    bool Ready(std::uint64_t completed) const
    {
        return recorded && submitted && detached && pendingSignals == 0 && !invalid && !signalFailed &&
               completed != UINT64_MAX && completed >= expected;
    }
    bool CanRelease(std::uint64_t completed) const
    {
        return (!submitted && detached) ||
            (submitted && detached && pendingSignals == 0 && !ambiguousSubmission && !signalFailed && completed != UINT64_MAX && completed >= expected);
    }
};
}
