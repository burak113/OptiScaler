#pragma once
#include <cstddef>

namespace NrdBridgeTitleCallbacks
{
enum class Method : unsigned { Pipeline, Dispatch, Reset, ClearState, Predication, Bundle, Indirect, Count };

// Debug/Streamline decorators can forward a title call through the same detour
// with another COM This. Keep the original/legacy call for both identities, but
// observe the outermost call once. Method-specific depths preserve setters that
// a runtime legitimately makes while forwarding another method.
class Scope
{
    inline static thread_local unsigned depths_[static_cast<unsigned>(Method::Count)] {};
    unsigned method_;
    bool enabled_, outermost_ = true;
  public:
    Scope(Method method, bool enabled) noexcept
        : method_(static_cast<unsigned>(method)), enabled_(enabled)
    {
        if (enabled_) outermost_ = depths_[method_]++ == 0;
    }
    ~Scope() { if (enabled_) --depths_[method_]; }
    bool Nested() const noexcept { return enabled_ && !outermost_; }
    Scope(const Scope&) = delete;
    Scope& operator=(const Scope&) = delete;
};
}
