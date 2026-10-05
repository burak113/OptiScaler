#include <pch.h>
#include "../../../upscalers/fsr31/FSRUpscaleSettings.h"

#include <array>
#include <cassert>
#include <iostream>

namespace
{
struct ConfigureStub
{
    ffxContext* expectedContext;
    uint64_t expectedKey;
    ffxReturnCode_t result = FFX_API_RETURN_OK;
    unsigned calls = 0;
    float receivedValue = 0.0f;

    ffxReturnCode_t operator()(ffxContext* context, const ffxConfigureDescHeader* header)
    {
        assert(context == expectedContext);
        assert(header && header->type == FFX_API_CONFIGURE_DESC_TYPE_UPSCALE_KEYVALUE);
        assert(header->pNext == nullptr);
        const auto* config = reinterpret_cast<const ffxConfigureDescUpscaleKeyValue*>(header);
        assert(config->key == expectedKey && config->ptr);
        receivedValue = *static_cast<const float*>(config->ptr);
        ++calls;
        return result;
    }
};
} // namespace

int main()
{
    using FSR31::ApplyUpscaleSetting;
    using FSR31::UpscaleSettingState;
    using FSR31::UpscaleSettings;

    ffxContext context = reinterpret_cast<ffxContext>(1);
    const std::array<uint64_t, 5> keys {
        FFX_API_CONFIGURE_UPSCALE_KEY_FVELOCITYFACTOR,
        FFX_API_CONFIGURE_UPSCALE_KEY_FREACTIVENESSSCALE,
        FFX_API_CONFIGURE_UPSCALE_KEY_FSHADINGCHANGESCALE,
        FFX_API_CONFIGURE_UPSCALE_KEY_FACCUMULATIONADDEDPERFRAME,
        FFX_API_CONFIGURE_UPSCALE_KEY_FMINDISOCCLUSIONACCUMULATION,
    };

    // Even a configured default must be applied once on a fresh context: an
    // initial float cache alone is not evidence of a successful SDK update.
    const std::array<float, 5> defaults { 1.0f, 1.0f, 1.0f, 0.333f, -0.333f };
    for (unsigned index = 0; index != keys.size(); ++index)
    {
        UpscaleSettingState state;
        ConfigureStub configure { &context, keys[index] };
        ApplyUpscaleSetting(&context, state, defaults[index], keys[index], configure);
        assert(configure.calls == 1 && state.hasAppliedValue);
        assert(state.appliedValue == defaults[index]);
        ApplyUpscaleSetting(&context, state, defaults[index], keys[index], configure);
        assert(configure.calls == 1);
    }

    // Exercise each real SDK key through the production descriptor builder.
    for (const auto key : keys)
    {
        UpscaleSettingState state;
        ConfigureStub configure { &context, key };
        auto update = ApplyUpscaleSetting(&context, state, 0.25f, key, configure);
        assert(!update.reportFailure && configure.calls == 1);
        assert(state.hasAppliedValue && state.appliedValue == 0.25f);
        assert(configure.receivedValue == 0.25f);

        for (unsigned frame = 0; frame != 120; ++frame)
            ApplyUpscaleSetting(&context, state, 0.25f, key, configure);
        assert(configure.calls == 1); // Successful unchanged values are no-ops.

        configure.result = FFX_API_RETURN_ERROR_RUNTIME_ERROR;
        update = ApplyUpscaleSetting(&context, state, 0.5f, key, configure);
        assert(update.reportFailure && !state.unsupported);
        assert(state.appliedValue == 0.25f && state.desiredValue == 0.5f);

        update = ApplyUpscaleSetting(&context, state, 0.5f, key, configure);
        assert(!update.reportFailure && configure.calls == 3);
        assert(state.appliedValue == 0.25f); // Failure must not poison the cache.

        // The next attempt must use a changed preference, not the failed value.
        configure.result = FFX_API_RETURN_OK;
        ApplyUpscaleSetting(&context, state, 0.75f, key, configure);
        assert(configure.calls == 4 && configure.receivedValue == 0.75f);
        assert(state.appliedValue == 0.75f && state.lastFailure == FFX_API_RETURN_OK);
        ApplyUpscaleSetting(&context, state, 0.75f, key, configure);
        assert(configure.calls == 4);

        // A subsequent failure is logged again after recovery.
        configure.result = FFX_API_RETURN_ERROR_RUNTIME_ERROR;
        assert(ApplyUpscaleSetting(&context, state, 0.5f, key, configure).reportFailure);
        ApplyUpscaleSetting(&context, state, 0.75f, key, configure);
        assert(configure.calls == 5 && state.lastFailure == FFX_API_RETURN_OK);
    }

    // None of these statuses proves the key unsupported. This includes an
    // invalid key/value flattened to RUNTIME_ERROR by the SDK's TRY2 macro.
    const std::array<ffxReturnCode_t, 6> retryableErrors {
        FFX_API_RETURN_ERROR, FFX_API_RETURN_ERROR_RUNTIME_ERROR, FFX_API_RETURN_NO_PROVIDER,
        FFX_API_RETURN_ERROR_MEMORY, FFX_API_RETURN_ERROR_PARAMETER, 999u,
    };
    for (const ffxReturnCode_t error : retryableErrors)
    {
        UpscaleSettingState state;
        ConfigureStub configure { &context, keys[0], error };
        assert(ApplyUpscaleSetting(&context, state, 0.5f, keys[0], configure).reportFailure);
        assert(!state.hasAppliedValue && !state.unsupported);
        assert(!ApplyUpscaleSetting(&context, state, 0.5f, keys[0], configure).reportFailure);
        assert(configure.calls == 2 && !state.hasAppliedValue);
        configure.result = FFX_API_RETURN_OK;
        ApplyUpscaleSetting(&context, state, 0.5f, keys[0], configure);
        assert(configure.calls == 3 && state.hasAppliedValue && state.appliedValue == 0.5f);
    }

    // Changing error categories is observable, while repeating one does not spam.
    {
        UpscaleSettingState state;
        ConfigureStub configure { &context, keys[0], FFX_API_RETURN_ERROR_PARAMETER };
        assert(ApplyUpscaleSetting(&context, state, 0.5f, keys[0], configure).reportFailure);
        configure.result = FFX_API_RETURN_ERROR_MEMORY;
        assert(ApplyUpscaleSetting(&context, state, 0.5f, keys[0], configure).reportFailure);
        assert(!ApplyUpscaleSetting(&context, state, 0.5f, keys[0], configure).reportFailure);
    }

    // Unsupported descriptor suppression, all five per-context cache resets,
    // and instance isolation use the exact aggregate owned by the feature.
    UpscaleSettings settings;
    const std::array<UpscaleSettingState*, 5> states {
        &settings.velocity, &settings.reactiveScale, &settings.shadingScale,
        &settings.accAddPerFrame, &settings.minDisOccAcc,
    };
    for (unsigned index = 0; index != keys.size(); ++index)
    {
        ConfigureStub configure { &context, keys[index], FFX_API_RETURN_ERROR_UNKNOWN_DESCTYPE };
        assert(ApplyUpscaleSetting(&context, *states[index], 0.5f, keys[index], configure).reportFailure);
        assert(states[index]->unsupported && !states[index]->hasAppliedValue);
        for (unsigned frame = 0; frame != 300; ++frame)
            assert(!ApplyUpscaleSetting(&context, *states[index], frame * 0.01f, keys[index], configure).reportFailure);
        assert(configure.calls == 1);
    }

    UpscaleSettings independent;
    ConfigureStub otherConfigure { &context, keys[0] };
    ApplyUpscaleSetting(&context, independent.velocity, 0.5f, keys[0], otherConfigure);
    assert(otherConfigure.calls == 1 && independent.velocity.hasAppliedValue);

    settings.ResetForContext(); // Called by production after successful context creation.
    for (unsigned index = 0; index != keys.size(); ++index)
    {
        ConfigureStub configure { &context, keys[index] };
        assert(!states[index]->unsupported && !states[index]->hasAppliedValue);
        ApplyUpscaleSetting(&context, *states[index], 0.5f, keys[index], configure);
        assert(configure.calls == 1 && states[index]->appliedValue == 0.5f);
    }
    settings.ResetForContext();
    ConfigureStub recreatedConfigure { &context, keys[0] };
    ApplyUpscaleSetting(&context, settings.velocity, 0.5f, keys[0], recreatedConfigure);
    assert(recreatedConfigure.calls == 1); // Prior applied value is also forgotten.
    assert(independent.velocity.hasAppliedValue); // Reset does not affect peers.

    std::cout << "SR settings: success caching, transient retry, changed desired values, descriptor suppression, "
                 "warning suppression, instance isolation, and context reset passed\n";
}
