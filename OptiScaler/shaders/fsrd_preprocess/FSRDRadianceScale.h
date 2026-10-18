#pragma once
#include <cstdint>

// One opt-in radiance-domain experiment for both NGX combined-color and native
// NRD inputs. OFF keeps each route's existing normalization, including NRD x256.
struct FSRDRadianceScaleSettings
{
    bool enabled = false;
    uint32_t diffuse = 16, specular = 256;
    bool operator==(const FSRDRadianceScaleSettings&) const = default;
};
inline bool ValidFSRDRadianceScale(uint32_t scale) noexcept
{
    return scale >= 1 && scale <= 4096 && (scale & (scale - 1)) == 0;
}
template<class Configuration> inline FSRDRadianceScaleSettings ReadFSRDRadianceScale(const Configuration& config)
{
    FSRDRadianceScaleSettings out;
    if constexpr (requires { config.FfxDenoiserRadianceScaleExperiment;
        config.FfxDenoiserRadianceScaleDiffuse; config.FfxDenoiserRadianceScaleSpecular; })
    {
        out.enabled = config.FfxDenoiserRadianceScaleExperiment.value_or_default();
        const auto diffuse = uint32_t(config.FfxDenoiserRadianceScaleDiffuse.value_or_default());
        const auto specular = uint32_t(config.FfxDenoiserRadianceScaleSpecular.value_or_default());
        if (ValidFSRDRadianceScale(diffuse)) out.diffuse = diffuse;
        if (ValidFSRDRadianceScale(specular)) out.specular = specular;
    }
    return out;
}
