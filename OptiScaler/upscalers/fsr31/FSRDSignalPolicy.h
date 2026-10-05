#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <string_view>

namespace FSRDSignals
{
enum Type : int
{
    DirectDiffuse,
    DirectSpecular,
    IndirectDiffuse,
    IndirectSpecular
};
constexpr uint32_t Bit(int type) { return type >= 0 && type < 4 ? 1u << type : 0u; }
constexpr uint32_t All = 15u;
constexpr uint32_t DiffuseBits = Bit(DirectDiffuse) | Bit(IndirectDiffuse);
constexpr uint32_t SpecularBits = Bit(DirectSpecular) | Bit(IndirectSpecular);
constexpr std::array<int, 4> Preferred { DirectDiffuse, IndirectSpecular, DirectSpecular, IndirectDiffuse };
constexpr const char* Names[] { "Direct Diffuse", "Direct Specular", "Indirect Diffuse", "Indirect Specular" };
constexpr int Count(uint32_t mask)
{
    return int((mask & 1u) != 0) + int((mask & 2u) != 0) + int((mask & 4u) != 0) + int((mask & 8u) != 0);
}
struct Layout
{
    std::array<int, 4> slots { -1, -1, -1, -1 };
    uint32_t mask = 0;
    int count = 0;
};
// Resolves the retired SignalCount/Signal1-4 keys. Keep valid requested assignments first.
// Fill missing/duplicate entries only after reserving later valid slots, so a missing guide
// cannot steal another slot's signal.
constexpr Layout Resolve(int count, std::array<int, 4> requested, uint32_t available = All)
{
    Layout result;
    count = std::clamp(count, 1, 4);
    available &= All;
    for (int i = 0; i < count; ++i)
        if ((available & Bit(requested[i])) && !(result.mask & Bit(requested[i])))
        {
            result.slots[i] = requested[i];
            result.mask |= Bit(requested[i]);
        }
    for (int i = 0; i < count; ++i)
        if (result.slots[i] < 0)
        {
            const int direct = requested[i] == IndirectSpecular  ? DirectSpecular
                               : requested[i] == IndirectDiffuse ? DirectDiffuse
                                                                 : -1;
            if ((available & Bit(direct)) && !(result.mask & Bit(direct)))
            {
                result.slots[i] = direct;
                result.mask |= Bit(direct);
                continue;
            }
            for (int candidate : Preferred)
                if ((available & Bit(candidate)) && !(result.mask & Bit(candidate)))
                {
                    result.slots[i] = candidate;
                    result.mask |= Bit(candidate);
                    break;
                }
        }
    // Compact the assignments if a previously saved 3/4-signal mode loses a guide.
    auto slots = result.slots;
    result.slots.fill(-1);
    for (int slot : slots)
        if (slot >= 0)
            result.slots[result.count++] = slot;
    return result;
}
constexpr bool SupportsUnsupportedAlbedo(uint32_t mask)
{
    return (mask & SpecularBits) == SpecularBits && (mask & DiffuseBits) != 0;
}

// The title supplies one combined colour, so Direct/Indirect is not a light split: it only
// chooses which RR path denoises a lobe. Indirect reads a hit distance from the signal's
// alpha; Direct does not. Split halves the lobe across both paths.
enum Route : int
{
    Auto,
    Direct,
    Indirect,
    Split
};
constexpr const char* RouteCodes[] { "auto", "direct", "indirect", "split" };
constexpr int RouteFromCode(const std::string_view code)
{
    for (int route = 0; route < 4; ++route)
        if (code == RouteCodes[route])
            return route;
    return Auto;
}

// What the user asks for. The RR layout is derived from it on every validated frame, never
// stored, so the menu preview and the running context cannot disagree.
struct Request
{
    int diffuse = Auto;
    int specular = Auto;
    bool denoiseDiffuse = true;
    bool denoiseSpecular = true;
    bool albedoFix = false;  // Unsupported-albedo recovery
    bool estimate = false;   // Primary view depth stands in for a missing hit distance
};

enum Note : uint32_t
{
    DiffuseNeedsDistance = 1u,  // Indirect/Split diffuse without a diffuse hit distance
    SpecularNeedsDistance = 2u, // Indirect/Split specular without a specular hit distance
    FixNeedsDistance = 4u,      // the albedo fix keeps the main specular on Indirect
    FixNeedsBothLobes = 8u,     // the albedo fix needs diffuse and specular denoising
};

struct Plan
{
    uint32_t mask = 0;
    bool albedoFix = false; // Direct Specular carries the unmodulated alternate
    uint32_t notes = 0;
    constexpr bool operator==(const Plan&) const = default;
};

// specularGuide/diffuseGuide: the title supplied that hit distance on a validated frame.
constexpr Plan MakePlan(Request request, bool specularGuide, bool diffuseGuide)
{
    Plan plan;
    if (!request.denoiseDiffuse && !request.denoiseSpecular)
        request.denoiseDiffuse = request.denoiseSpecular = true;
    const bool specularDistance = specularGuide || request.estimate;
    const bool diffuseDistance = diffuseGuide || request.estimate;
    const auto lobe = [&plan](int route, bool distance, int direct, int indirect, uint32_t note)
    {
        route = std::clamp(route, int(Auto), int(Split));
        if (route == Direct) return Bit(direct);
        if (!distance)
        {
            if (route != Auto) plan.notes |= note;
            return Bit(direct);
        }
        return route == Split ? Bit(direct) | Bit(indirect) : Bit(indirect);
    };
    if (request.denoiseDiffuse)
        plan.mask |= lobe(request.diffuse, diffuseDistance, DirectDiffuse, IndirectDiffuse, DiffuseNeedsDistance);
    if (request.albedoFix)
    {
        // The alternate is denoised as Direct Specular, so the main specular needs Indirect.
        if (!request.denoiseDiffuse || !request.denoiseSpecular)
            plan.notes |= FixNeedsBothLobes;
        else if (!specularDistance)
            plan.notes |= FixNeedsDistance;
        else
        {
            plan.albedoFix = true;
            plan.mask |= SpecularBits;
            return plan;
        }
    }
    if (request.denoiseSpecular)
        plan.mask |= lobe(request.specular, specularDistance, DirectSpecular, IndirectSpecular, SpecularNeedsDistance);
    return plan;
}

// Maps the retired SignalCount/Signal1-4 or Diffuse/SpecularSignalType keys (0 Direct,
// 1 Indirect, -1 unset) to routing. Every saved layout survives with all guides present.
constexpr Request FromLegacy(Request request, bool hasLayout, int count, std::array<int, 4> slots, int diffuseType,
                             int specularType)
{
    if (!hasLayout)
    {
        if (diffuseType >= 0) request.diffuse = diffuseType ? Indirect : Direct;
        if (specularType >= 0) request.specular = specularType ? Indirect : Direct;
        return request;
    }
    const uint32_t mask = Resolve(count, slots).mask;
    // The Quality profile wrote this layout for the albedo fix; it was never a routing choice.
    if (request.albedoFix && mask == (Bit(DirectDiffuse) | SpecularBits))
        return request;
    const auto route = [](uint32_t bits, int direct, int indirect)
    {
        return bits == (Bit(direct) | Bit(indirect)) ? Split : bits == Bit(indirect) ? Indirect : Direct;
    };
    request.denoiseDiffuse = (mask & DiffuseBits) != 0;
    request.denoiseSpecular = (mask & SpecularBits) != 0;
    if (request.denoiseDiffuse) request.diffuse = route(mask & DiffuseBits, DirectDiffuse, IndirectDiffuse);
    // With a running fix, both specular slots were the main signal and its alternate.
    if (request.denoiseSpecular && !(request.albedoFix && SupportsUnsupportedAlbedo(mask)))
        request.specular = route(mask & SpecularBits, DirectSpecular, IndirectSpecular);
    return request;
}

// Runtime -> menu report, packed into one atomic word.
struct Status
{
    bool observed = false;       // a frame passed validation
    bool specularGuide = false;  // title hit distances seen on a validated frame
    bool diffuseGuide = false;
    bool albedoFixActive = false; // the fix runs this frame (modulation and additive split allow it)
    Plan plan;

    constexpr uint32_t Pack() const
    {
        return (observed ? 1u : 0u) | (specularGuide ? 2u : 0u) | (diffuseGuide ? 4u : 0u) |
               (albedoFixActive ? 8u : 0u) | (plan.albedoFix ? 16u : 0u) | ((plan.mask & All) << 8) |
               ((plan.notes & 15u) << 12);
    }
    static constexpr Status Unpack(uint32_t word)
    {
        Status status;
        status.observed = word & 1u;
        status.specularGuide = word & 2u;
        status.diffuseGuide = word & 4u;
        status.albedoFixActive = word & 8u;
        status.plan.albedoFix = word & 16u;
        status.plan.mask = (word >> 8) & All;
        status.plan.notes = (word >> 12) & 15u;
        return status;
    }
};

// Config adapters stay templates so this header compiles without Config.h in the tests.
template <class C> Request RequestFrom(const C& cfg)
{
    return { std::clamp(cfg.FfxDenoiserDiffuseRoute.value_or_default(), int(Auto), int(Split)),
             std::clamp(cfg.FfxDenoiserSpecularRoute.value_or_default(), int(Auto), int(Split)),
             cfg.FfxDenoiserDenoiseDiffuse.value_or_default(),
             cfg.FfxDenoiserDenoiseSpecular.value_or_default(),
             cfg.FfxDenoiserUnsupportedAlbedoRecovery.value_or_default(),
             cfg.FfxDenoiserEstimateHitDistances.value_or_default() };
}
// The alternate replaces the full-strength specular reconstruction, so the fix runs only at
// the default 1/1 modulation and without the additive split.
template <class C> bool AlbedoFixAllowed(const C& cfg)
{
    return cfg.FfxDenoiserSpecularAlbedoDemodulation.value_or_default() == 1.0f &&
           cfg.FfxDenoiserDiffuseAlbedoModulation.value_or_default() == 1.0f &&
           cfg.FfxDenoiserAdditiveLightSplit.value_or_default() == 0.0f;
}
} // namespace FSRDSignals
