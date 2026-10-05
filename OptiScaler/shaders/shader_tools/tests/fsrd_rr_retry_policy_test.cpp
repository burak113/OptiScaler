#include "../../../upscalers/fsr31/FSRDRetryPolicy.h"
#include "../../../upscalers/fsr31/FSRDResultClassification.h"
#include <array>
#include <cassert>
#include <iostream>

int main()
{
    using FSRD::RRResult;
    using FSRD::RRRetryPolicy;

    for (bool dynamicInput : { false, true })
    {
        assert(FSRD::ClassifyRRApiFailure(FFX_API_RETURN_OK, dynamicInput, false) == RRResult::Success);
        assert(FSRD::ClassifyRRApiFailure(FFX_API_RETURN_ERROR_PARAMETER, dynamicInput, false) ==
               (dynamicInput ? RRResult::RetryableInputFailure : RRResult::UnsupportedProvider));
        for (const auto code : { FFX_API_RETURN_NO_PROVIDER, FFX_API_RETURN_ERROR_UNKNOWN_DESCTYPE })
            assert(FSRD::ClassifyRRApiFailure(code, dynamicInput, false) == RRResult::UnsupportedProvider);
        for (const auto code : { FFX_API_RETURN_ERROR, FFX_API_RETURN_ERROR_RUNTIME_ERROR,
                                 FFX_API_RETURN_ERROR_MEMORY })
            assert(FSRD::ClassifyRRApiFailure(code, dynamicInput, false) == RRResult::NeedsRecreation);
        // Device loss takes precedence even if the API returned OK or a parameter error.
        for (ffxReturnCode_t code = FFX_API_RETURN_OK; code <= FFX_API_RETURN_ERROR_PARAMETER; ++code)
            assert(FSRD::ClassifyRRApiFailure(code, dynamicInput, true) == RRResult::DeviceLost);
        assert(FSRD::ClassifyRRApiFailure(999, dynamicInput, false) == RRResult::NeedsRecreation);
    }

    // One missing-resource frame must recover immediately when the title fixes it.
    RRRetryPolicy policy;
    assert(policy.CanAttempt());
    policy.Record(RRResult::RetryableInputFailure);
    assert(!policy.IsLatched());
    assert(policy.CanAttempt());
    policy.Record(RRResult::Success);
    for (unsigned frame = 0; frame != 120; ++frame)
        assert(policy.CanAttempt());

    // Persistently rejected inputs must neither spin every frame nor become
    // permanently faulted. Bounded probes must still admit corrected inputs.
    unsigned attempts = 0;
    unsigned longestGap = 0;
    unsigned gap = 0;
    for (unsigned frame = 0; frame != 5000; ++frame)
    {
        if (policy.CanAttempt())
        {
            ++attempts;
            longestGap = std::max(longestGap, gap);
            gap = 0;
            policy.Record(RRResult::RetryableInputFailure);
        }
        else
            ++gap;
        assert(!policy.IsLatched());
    }
    assert(attempts > 80 && attempts < 100);
    assert(longestGap == RRRetryPolicy::MaxSkippedFrames);
    bool recovered = false;
    for (unsigned frame = 0; frame <= RRRetryPolicy::MaxSkippedFrames; ++frame)
    {
        if (policy.CanAttempt())
        {
            policy.Record(RRResult::Success);
            recovered = true;
            break;
        }
    }
    assert(recovered && policy.Result() == RRResult::Success);
    assert(policy.SkippedFramesRemaining() == 0 && policy.CanAttempt());

    // Success must reset the failure streak, so a new one-frame outage does not
    // inherit a previous session's long backoff.
    policy.Record(RRResult::RetryableInputFailure);
    assert(policy.CanAttempt());

    const std::array<RRResult, 3> latchedFailures {{
        RRResult::NeedsRecreation, RRResult::UnsupportedProvider, RRResult::DeviceLost
    }};
    for (const auto failure : latchedFailures)
    {
        policy.Reset();
        policy.Record(failure);
        for (unsigned frame = 0; frame != 5000; ++frame)
        {
            assert(!policy.CanAttempt());
            // A successful fallback or later missing input cannot reopen RR.
            policy.Record(RRResult::Success);
            policy.Record(RRResult::RetryableInputFailure);
            assert(policy.Result() == failure);
        }
        policy.Reset(); // A successfully recreated context explicitly unlocks RR.
        assert(!policy.IsLatched() && policy.CanAttempt());
    }

    policy.Record(RRResult::UnsupportedProvider);
    policy.Record(RRResult::DeviceLost);
    assert(policy.Result() == RRResult::DeviceLost && !policy.CanAttempt());
    policy.Record(RRResult::NeedsRecreation);
    assert(policy.Result() == RRResult::DeviceLost);
    std::cout << "RR API classification and retry policy: transient recovery, bounded probes, and permanent latches passed\n";
}
