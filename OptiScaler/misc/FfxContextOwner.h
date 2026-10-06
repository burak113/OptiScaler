#pragma once

#include <ffx_api.h>
#include <memory>

// Owns one FFX provider context (SR, RR). The provider records into the title's command
// lists, and that recorded work reads the context's internal resources; D3D12 keeps none of
// them alive. A recorded-lifetime feature therefore passes its owner as a lease of every list
// it dispatches into (RecordedComputeLease): the context is destroyed only once the feature,
// every recording that can still be (re)submitted and every unfinished submission let go.
// The last release may happen on any thread (a list Reset/Release or a queue submission).
class FfxContextOwner
{
  public:
    using DestroyFn = ffxReturnCode_t (*)(ffxContext*, const ffxAllocationCallbacks*);
    using ShutdownFn = bool (*)();
    using ReportFn = void (*)(const char* name, ffxContext context, ffxReturnCode_t result);

    FfxContextOwner(ffxContext context, const char* name, DestroyFn destroy, ShutdownFn shuttingDown,
                    ReportFn report = nullptr) noexcept
        : _context(context), _name(name), _destroy(destroy), _shuttingDown(shuttingDown), _report(report)
    {
    }
    FfxContextOwner(const FfxContextOwner&) = delete;
    FfxContextOwner& operator=(const FfxContextOwner&) = delete;

    ~FfxContextOwner()
    {
        // Provider modules may already be gone during process teardown; the destructors
        // this replaces skipped the call there as well.
        if (_context == nullptr || _destroy == nullptr || (_shuttingDown && _shuttingDown()))
            return;
        ffxContext context = _context;
        const ffxReturnCode_t result = _destroy(&context, nullptr);
        if (_report)
            _report(_name, _context, result);
    }

    ffxContext Get() const noexcept { return _context; }

  private:
    ffxContext _context;
    const char* _name;
    DestroyFn _destroy;
    ShutdownFn _shuttingDown;
    ReportFn _report;
};
