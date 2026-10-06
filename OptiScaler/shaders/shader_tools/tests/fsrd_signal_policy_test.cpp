#include "../../../upscalers/fsr31/FSRDSignalPolicy.h"
#include <cstdlib>
#include <iostream>

static unsigned checks = 0;
#define CHECK(x)                                                                                                       \
    do                                                                                                                 \
    {                                                                                                                  \
        ++checks;                                                                                                      \
        if (!(x))                                                                                                      \
        {                                                                                                              \
            std::cerr << "FAIL line " << __LINE__ << ": " #x "\n";                                                     \
            std::exit(1);                                                                                              \
        }                                                                                                              \
    } while (false)

using namespace FSRDSignals;

// Independent restatement of the routing rules the menu documents.
static uint32_t ExpectedLobe(int route, bool distance, int direct, int indirect)
{
    route = std::clamp(route, 0, 3);
    if (route == Direct || !distance) return Bit(direct);
    if (route == Split) return Bit(direct) | Bit(indirect);
    return Bit(indirect);
}

static void CheckResolve()
{
    CHECK(Resolve(1, { IndirectSpecular, -1, -1, -1 }, Bit(DirectDiffuse) | Bit(DirectSpecular)).mask ==
          Bit(DirectSpecular));
    CHECK(Resolve(1, { IndirectDiffuse, -1, -1, -1 }, Bit(DirectDiffuse) | Bit(DirectSpecular)).mask ==
          Bit(DirectDiffuse));
    for (uint32_t available : { All, Bit(DirectDiffuse) | Bit(DirectSpecular), All & ~Bit(IndirectDiffuse) })
        for (int count = -1; count <= 5; ++count)
            for (int a = -1; a < 5; ++a)
                for (int b = -1; b < 5; ++b)
                    for (int c = -1; c < 5; ++c)
                        for (int d = -1; d < 5; ++d)
                        {
                            const std::array<int, 4> requested { a, b, c, d };
                            const auto layout = Resolve(count, requested, available);
                            CHECK(layout.count == std::min(std::clamp(count, 1, 4), Count(available)));
                            CHECK(Count(layout.mask) == layout.count);
                            CHECK((layout.mask & available) == layout.mask);
                            for (int i = 0; i < std::clamp(count, 1, 4); ++i)
                                if (available & Bit(requested[i]))
                                    CHECK(layout.mask & Bit(requested[i]));
                        }
}

static void CheckPlan()
{
    for (int diffuse = -1; diffuse <= 4; ++diffuse)
        for (int specular = -1; specular <= 4; ++specular)
            for (int flags = 0; flags < 128; ++flags)
            {
                const Request request { diffuse,          specular,         (flags & 1) != 0, (flags & 2) != 0,
                                        (flags & 4) != 0, (flags & 8) != 0, (flags & 64) != 0 };
                const bool specularGuide = flags & 16, diffuseGuide = flags & 32;
                const Plan plan = MakePlan(request, specularGuide, diffuseGuide);
                const bool both = !request.denoiseDiffuse && !request.denoiseSpecular;
                const bool denoiseDiffuse = request.denoiseDiffuse || both;
                const bool denoiseSpecular = request.denoiseSpecular || both;
                const bool specularDistance = specularGuide || request.estimate;
                const bool diffuseDistance = diffuseGuide || request.estimate;

                const uint32_t diffuseBits =
                    denoiseDiffuse ? ExpectedLobe(diffuse, diffuseDistance, DirectDiffuse, IndirectDiffuse) : 0u;
                const bool fix = request.albedoFix && denoiseDiffuse && denoiseSpecular && specularDistance;
                const bool diffuseCopy = fix && request.fixDiffuse;
                const uint32_t specularBits = fix ? SpecularBits
                    : denoiseSpecular ? ExpectedLobe(specular, specularDistance, DirectSpecular, IndirectSpecular)
                                      : 0u;
                // The fix denoises an unmodulated copy of each fixed lobe in its second slot;
                // without the diffuse copy the diffuse lobe keeps its own route.
                CHECK(plan.mask == (diffuseCopy ? All : diffuseBits | specularBits));
                CHECK(plan.albedoFix == fix && plan.diffuseCopy == diffuseCopy);
                CHECK(!plan.albedoFix || SupportsUnsupportedAlbedo(plan.mask));
                // A plan made from this frame's guides can be fed on this frame...
                CHECK((plan.mask & ~Feedable(plan, request.estimate, specularGuide, diffuseGuide)) == 0);
                // ...and a guide dropout stops only Indirect paths that read the title's distance.
                const uint32_t needsTitle = Bit(IndirectSpecular) | (diffuseCopy ? 0u : Bit(IndirectDiffuse));
                CHECK((plan.mask & ~Feedable(plan, request.estimate, false, false)) ==
                      (request.estimate ? 0u : plan.mask & needsTitle));
                // A route that needs a distance falls back to Direct and says why.
                const auto routed = [](int route) { route = std::clamp(route, 0, 3); return route == Indirect || route == Split; };
                CHECK(bool(plan.notes & DiffuseNeedsDistance) ==
                      (!diffuseCopy && denoiseDiffuse && routed(diffuse) && !diffuseDistance));
                CHECK(bool(plan.notes & SpecularNeedsDistance) ==
                      (!fix && denoiseSpecular && routed(specular) && !specularDistance));
                CHECK(bool(plan.notes & FixNeedsBothLobes) == (request.albedoFix && !(denoiseDiffuse && denoiseSpecular)));
                CHECK(bool(plan.notes & FixNeedsDistance) ==
                      (request.albedoFix && denoiseDiffuse && denoiseSpecular && !specularDistance));
                // The packed runtime report carries the plan unchanged.
                for (int bits = 0; bits < 16; ++bits)
                {
                    Status status { (bits & 1) != 0, (bits & 2) != 0, (bits & 4) != 0, (bits & 8) != 0, plan };
                    const Status unpacked = Status::Unpack(status.Pack());
                    CHECK(unpacked.plan == plan && unpacked.observed == status.observed &&
                          unpacked.specularGuide == status.specularGuide &&
                          unpacked.diffuseGuide == status.diffuseGuide &&
                          unpacked.albedoFixActive == status.albedoFixActive);
                }
            }
}

static void CheckLegacy()
{
    for (bool fix : { false, true })
        for (int count = 1; count <= 4; ++count)
            for (int a = 0; a < 4; ++a)
                for (int b = 0; b < 4; ++b)
                    for (int c = 0; c < 4; ++c)
                        for (int d = 0; d < 4; ++d)
                        {
                            Request old;
                            old.albedoFix = fix;
                            const std::array<int, 4> slots { a, b, c, d };
                            const uint32_t legacy = Resolve(count, slots).mask;
                            const Request request = FromLegacy(old, true, count, slots, 1, 0);
                            const Plan plan = MakePlan(request, true, true);
                            CHECK(request.albedoFix == fix && !request.estimate);
                            if (!fix)
                                CHECK(plan.mask == legacy && !plan.albedoFix);
                            else if (legacy == (Bit(DirectDiffuse) | SpecularBits))
                                // The Quality profile's layout becomes Auto routing plus the fix.
                                CHECK(request.diffuse == Auto && request.specular == Auto && plan.albedoFix &&
                                      plan.mask == All);
                            else if ((legacy & DiffuseBits) && (legacy & SpecularBits))
                                // The fix now adds the slots it needs instead of pausing.
                                CHECK(plan.albedoFix && plan.diffuseCopy && plan.mask == All);
                            else
                                CHECK(!plan.albedoFix && plan.mask == legacy && (plan.notes & FixNeedsBothLobes));
                            // Without guides a legacy Indirect choice falls back to Direct, as the slot did.
                            const Plan unguided = MakePlan(request, false, false);
                            CHECK((unguided.mask & (Bit(IndirectDiffuse) | Bit(IndirectSpecular))) == 0);
                        }
    for (int diffuseType = -1; diffuseType <= 1; ++diffuseType)
        for (int specularType = -1; specularType <= 1; ++specularType)
        {
            const Request request = FromLegacy({}, false, 2, { 0, 3, 1, 2 }, diffuseType, specularType);
            CHECK(request.diffuse == (diffuseType < 0 ? Auto : diffuseType ? Indirect : Direct));
            CHECK(request.specular == (specularType < 0 ? Auto : specularType ? Indirect : Direct));
            CHECK(request.denoiseDiffuse && request.denoiseSpecular);
        }
    for (int route = 0; route < 4; ++route)
        CHECK(RouteFromCode(RouteCodes[route]) == route);
    CHECK(RouteFromCode("both") == Auto);
}

template <class T> struct Setting
{
    T value;
    T value_or_default() const { return value; }
};
struct FakeConfig
{
    Setting<int> FfxDenoiserDiffuseRoute { 9 }, FfxDenoiserSpecularRoute { -3 };
    Setting<bool> FfxDenoiserDenoiseDiffuse { true }, FfxDenoiserDenoiseSpecular { false };
    Setting<bool> FfxDenoiserUnsupportedAlbedoRecovery { true }, FfxDenoiserEstimateHitDistances { true };
    Setting<bool> FfxDenoiserAlbedoBleedFixDiffuse { false };
    Setting<float> FfxDenoiserSpecularAlbedoDemodulation { 1.0f }, FfxDenoiserDiffuseAlbedoModulation { 1.0f };
    Setting<float> FfxDenoiserAdditiveLightSplit { 0.0f };
};

static void CheckConfigAdapters()
{
    FakeConfig cfg;
    const Request request = RequestFrom(cfg);
    CHECK(request.diffuse == Split && request.specular == Auto);
    CHECK(request.denoiseDiffuse && !request.denoiseSpecular && request.albedoFix && request.estimate &&
          !request.fixDiffuse);
    CHECK(AlbedoFixAllowed(cfg));
    cfg.FfxDenoiserDiffuseAlbedoModulation.value = 0.5f;
    CHECK(!AlbedoFixAllowed(cfg));
    cfg.FfxDenoiserDiffuseAlbedoModulation.value = 1.0f;
    cfg.FfxDenoiserAdditiveLightSplit.value = 0.25f;
    CHECK(!AlbedoFixAllowed(cfg));
}

int main()
{
    CheckResolve();
    CheckPlan();
    CheckLegacy();
    CheckConfigAdapters();
    std::cout << checks << " signal-plan checks passed\n";
}
