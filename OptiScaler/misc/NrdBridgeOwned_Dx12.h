#pragma once
#include "resource_tracking/FrameSurvey_Dx12.h"
#include <memory>
#include <utility>

namespace NrdBridge
{
// Keep the internal guard around delete itself, including automatic COM-member
// destruction. A local guard in a destructor body ends before member destructors.
template<class T, class... Args> std::shared_ptr<T> MakeOwnedShared(Args&&... args)
{
    return std::shared_ptr<T>(new T(std::forward<Args>(args)...), [](T* object) {
        FrameSurvey::ScopedInternal internal;
        delete object;
    });
}
}
