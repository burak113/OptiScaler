#pragma once

template <typename FeatureType> struct ContextData
{
    std::unique_ptr<FeatureType> feature;
    std::string featureKey; // Optional OptiKey identifier - used in DX12
    NVSDK_NGX_Feature featureID;
    NVSDK_NGX_Parameter* createParams = nullptr;
    int changeBackendCounter = 0;
};
