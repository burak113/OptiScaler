#pragma once

template <typename FeatureType> struct ContextData
{
    std::unique_ptr<FeatureType> feature;
    Upscaler featureKey = Upscaler::Reset; // Backend the feature was created with - used in DX12
    NVSDK_NGX_Feature featureID;
    NVSDK_NGX_Parameter* createParams = nullptr;
    bool ownsCreateParams = false; // DX12 recreation must not destroy a borrowed game table.
    bool evaluationFailed = false;
    int changeBackendCounter = 0;
};
