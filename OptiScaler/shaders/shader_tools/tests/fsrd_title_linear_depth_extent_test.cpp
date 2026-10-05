#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <DirectXMath.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sl_core_types.h>
#include <ffx_api.h>
#include <ffx_api_types.h>
#include "FSRDTaggedResourceExtent.h"

using Microsoft::WRL::ComPtr;
using DirectX::XMUINT2;

#define LOG_DEBUG(...) ((void)0)
#define LOG_WARN(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
#define LOG_INFO(...) ((void)0)

#include "fsrd_title_depth_metadata.inc"

std::string GetD3D12DebugObjectName(ID3D12Resource*) { return {}; }
#include "fsrd_title_depth_helpers.inc"

struct NVSDK_NGX_Parameter {};
struct Config
{
    struct Setting
    {
        bool value = true;
        bool value_or_default() const { return value; }
    } FfxDenoiserUseTitleLinearDepth;
    static Config* Instance() { static Config config; return &config; }
};

struct Harness
{
    enum class TagStatePolicy : uint8_t { RequireShaderRead, AnyDeclaredState, AllowCommonTransition };
    std::array<uint64_t, static_cast<size_t>(RRTaggedSignal::Count)> _lastConsumedSLTagUpdates {};
    std::array<uint32_t, static_cast<size_t>(RRTaggedSignal::Count)> _lastConsumedSLTagFrames {};
    ComPtr<ID3D12Resource> _titleLinearDepthTaggedResource, _responsivityMaskTaggedResource;
    struct
    {
        struct { ID3D12Resource* InTitleLinearDepth = nullptr; ID3D12Resource* InResponsivityMask = nullptr; } Resources;
        XMUINT2 TitleLinearDepthBase {};
        uint32_t TitleLinearDepthState = 0, TitleLinearDepthDeclaredState = 0;
    } _convDesc;
    #include "fsrd_title_depth_methods.inc"
};

static unsigned checks = 0;
static void need(bool ok, const char* text)
{
    ++checks;
    if (!ok) throw std::runtime_error(text);
}
static void hr(HRESULT result) { need(SUCCEEDED(result), "D3D12 call failed"); }

static ComPtr<ID3D12Resource> texture(ID3D12Device* device, DXGI_FORMAT format)
{
    D3D12_RESOURCE_DESC desc {};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = desc.Height = 2048;
    desc.DepthOrArraySize = desc.MipLevels = 1;
    desc.SampleDesc.Count = 1;
    desc.Format = format;
    D3D12_HEAP_PROPERTIES heap {};
    heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    ComPtr<ID3D12Resource> result;
    hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
                                      D3D12_RESOURCE_STATE_COMMON, nullptr, IID_PPV_ARGS(&result)));
    return result;
}

static constexpr size_t DepthIndex = static_cast<size_t>(RRTaggedSignal::LinearDepth);
static RRD3D12SignalTagSnapshot snapshot(ID3D12Resource* resource, sl::Extent extent = {},
                                       uint32_t frame = 11, uint32_t state = D3D12_RESOURCE_STATE_COMMON)
{
    sl::Resource native(sl::ResourceType::eTex2d, resource, state);
    sl::ResourceTag tag(&native, sl::kBufferTypeLinearDepth, sl::ResourceLifecycle::eValidUntilEvaluate, &extent);
    RRD3D12SignalTagSnapshot result {};
    result.activeEvaluationFrame = frame;
    result.activeEvaluationViewport = 3;
    auto& entry = result.resources[DepthIndex];
    entry.resource = resource;
    entry.diagnostic = CaptureSLResourceTag(tag, frame, 3, RRTagSource::SetTagForFrame);
    entry.diagnostic.updateCount = 1;
    return result;
}

static bool bind(Harness& host, const RRD3D12SignalTagSnapshot& tags,
                 uint32_t width = 1280, uint32_t height = 720)
{
    host.AcquireOptionalInputs({}, tags, width, height);
    return host._convDesc.Resources.InTitleLinearDepth != nullptr;
}

static void checkCoverage(ID3D12Resource* resource)
{
    Harness host;
    auto shortTag = snapshot(resource, { 0, 0, 640, 360 });
    need(FSRD::HasValidTaggedResourceExtent(shortTag.resources[DepthIndex].diagnostic),
         "small extent is coherent but insufficient for linear depth");
    need(!bind(host, shortTag), "640x360 tag on 2048x2048 storage must reject 1280x720 render coverage");
    need(!host._titleLinearDepthTaggedResource && host._convDesc.TitleLinearDepthState == 0,
         "rejection keeps the derived-depth path active");
    need(bind(host, snapshot(resource, { 0, 0, 1280, 720 })), "exact effective coverage accepted");
    need(bind(host, snapshot(resource, { 0, 0, 1536, 1024 })), "oversized effective coverage accepted");
    need(bind(host, snapshot(resource, { 32, 64, 1536, 1024 })), "nonzero-base coverage accepted");
    need(host._convDesc.TitleLinearDepthBase.x == 64 && host._convDesc.TitleLinearDepthBase.y == 32,
         "selected linear-depth tag base preserved");
    need(bind(host, snapshot(resource, { 2048 - 720, 2048 - 1280, 1280, 720 })),
         "tag touching both physical boundaries accepted");
    need(!bind(host, snapshot(resource, { 0, 0, 1279, 720 })), "one-pixel width shortfall refused");
    need(!bind(host, snapshot(resource, { 0, 0, 1280, 719 })), "one-pixel height shortfall refused");
    need(!host._convDesc.Resources.InTitleLinearDepth && !host._titleLinearDepthTaggedResource &&
         host._convDesc.TitleLinearDepthBase.x == 0 && host._convDesc.TitleLinearDepthBase.y == 0,
         "an unusable next-frame tag clears the prior binding and base");
    need(!bind(host, snapshot(resource, { 0, 900, 1280, 720 }), 640, 360),
         "whole logical tag outside physical storage rejected even when render subrect fits");
    need(!bind(host, snapshot(resource, { 1500, 0, 1280, 720 })), "tag bottom outside physical storage rejected");
    need(!bind(host, snapshot(resource, { 0, UINT32_MAX - 15, 1280, 720 })), "32-bit base-plus-width wrap rejected");
    need(!bind(host, snapshot(resource, { UINT32_MAX - 15, 0, 1280, 720 })), "32-bit base-plus-height wrap rejected");

    auto whole = snapshot(resource);
    need(!whole.resources[DepthIndex].diagnostic.usesExtent && bind(host, whole),
         "all-zero absent extent uses whole native texture");
    need(!bind(host, whole, 0, 720) && !bind(host, whole, 1280, 0), "empty render coverage rejected");
    need(!bind(host, whole, 2049, 720) && !bind(host, whole, 1280, 2049), "native-full coverage still bounded");
    whole.resources[DepthIndex].diagnostic.extentLeft = 1;
    need(!bind(host, whole), "absent extent with conflicting nonzero base rejected");
    whole = snapshot(resource);
    whole.resources[DepthIndex].diagnostic.effectiveWidth = 1280;
    need(!bind(host, whole), "absent extent must retain coherent native-full dimensions");

    for (const sl::Extent extent : { sl::Extent { 0, 0, 0, 720 }, sl::Extent { 0, 0, 1280, 0 },
                                   sl::Extent { 1, 0, 0, 0 }, sl::Extent { 0, 1, 0, 0 } })
    {
        const auto malformed = snapshot(resource, extent);
        need(malformed.resources[DepthIndex].diagnostic.usesExtent,
             "capture preserves partial-zero explicit extent");
        need(!bind(host, malformed), "partial-zero explicit extent rejected");
    }
    whole = snapshot(resource);
    whole.resources[DepthIndex].diagnostic.usesExtent = true;
    whole.resources[DepthIndex].diagnostic.effectiveWidth = 0;
    whole.resources[DepthIndex].diagnostic.effectiveHeight = 0;
    need(!bind(host, whole), "explicit empty effective region rejected");
    need(bind(host, snapshot(resource, { 0, 0, 1280, 720 }, 12)),
         "valid later-frame tag recovers after optional extent rejection");
}

static void checkAcquisition(ID3D12Resource* resource, ID3D12Resource* other)
{
    Harness host;
    const auto fresh = snapshot(resource, { 0, 0, 1280, 720 });
    auto altered = fresh;
    altered.resources[DepthIndex].diagnostic.frameIndex = 10;
    need(!bind(host, altered), "stale modern frame still refused");
    altered = fresh; altered.resources[DepthIndex].diagnostic.viewport = 4;
    need(!bind(host, altered), "cross-viewport tag still refused");
    altered = fresh; altered.activeEvaluationFrame = UINT32_MAX;
    need(!bind(host, altered), "uncorrelated active frame still refused");
    altered = fresh; altered.activeEvaluationViewport = UINT32_MAX;
    need(!bind(host, altered), "uncorrelated active viewport still refused");
    altered = fresh; altered.resources[DepthIndex].diagnostic.lifecycle = sl::ResourceLifecycle::eOnlyValidNow;
    need(!bind(host, altered), "OnlyValidNow outside active EvaluateFeature still refused");
    altered.resources[DepthIndex].diagnostic.source = RRTagSource::EvaluateFeature;
    need(bind(host, altered), "OnlyValidNow during active EvaluateFeature accepted");
    need(bind(host, fresh) && host._convDesc.TitleLinearDepthDeclaredState == D3D12_RESOURCE_STATE_COMMON,
         "COMMON transition allowance and declared state retained");
    altered = fresh; altered.resources[DepthIndex].diagnostic.state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    need(bind(host, altered), "declared compute shader-readable state accepted");
    altered.resources[DepthIndex].diagnostic.state = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
    need(!bind(host, altered), "pixel-only state still refused");
    altered.resources[DepthIndex].diagnostic.state = UINT32_MAX;
    need(!bind(host, altered), "undeclared state still refused");
    altered = fresh; altered.resources[DepthIndex].diagnostic.resourceAddress = other;
    need(!bind(host, altered), "retained native identity mismatch still refused");
    altered = fresh; altered.resources[DepthIndex].diagnostic.nativeWidth = 2047;
    need(!bind(host, altered), "native descriptor mismatch still refused");
    altered = fresh; altered.resources[DepthIndex].resource.Reset();
    need(!bind(host, altered), "missing retained resource still refused");
    altered = fresh; altered.resources[DepthIndex].diagnostic.present = false;
    need(!bind(host, altered), "absent tag still refused");
    altered = fresh; altered.resources[DepthIndex].diagnostic.observed = false;
    need(!bind(host, altered), "unobserved tag still refused");

    auto legacy = fresh;
    legacy.resources[DepthIndex].diagnostic.frameIndex = UINT32_MAX;
    legacy.resources[DepthIndex].diagnostic.source = RRTagSource::SetTag;
    legacy.resources[DepthIndex].diagnostic.updateCount = 7;
    need(bind(host, legacy) && bind(host, legacy), "legacy repeated same-frame acquisition remains valid");
    legacy.activeEvaluationFrame = 12;
    need(!bind(host, legacy), "legacy stale next-frame reuse still refused");
    ++legacy.resources[DepthIndex].diagnostic.updateCount;
    need(bind(host, legacy), "fresh legacy update recovers in new frame");
    const uint64_t consumedUpdate = host._lastConsumedSLTagUpdates[DepthIndex];
    const uint32_t consumedFrame = host._lastConsumedSLTagFrames[DepthIndex];
    legacy.activeEvaluationFrame = 13;
    ++legacy.resources[DepthIndex].diagnostic.updateCount;
    legacy.resources[DepthIndex].diagnostic.effectiveWidth = 0;
    need(!bind(host, legacy), "malformed legacy extent refused");
    need(host._lastConsumedSLTagUpdates[DepthIndex] == consumedUpdate &&
         host._lastConsumedSLTagFrames[DepthIndex] == consumedFrame,
         "malformed geometry is not recorded as successful legacy consumption");

    Config::Instance()->FfxDenoiserUseTitleLinearDepth.value = false;
    need(!bind(host, fresh), "title linear depth remains opt-in");
    Config::Instance()->FfxDenoiserUseTitleLinearDepth.value = true;
    need(bind(host, fresh), "opt-in binding resumes without permanent failure");
}

int main() try
{
    ComPtr<IDXGIFactory4> factory; hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> warp; hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));
    ComPtr<ID3D12Device> device;
    hr(D3D12CreateDevice(warp.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)));
    const auto r32 = texture(device.Get(), DXGI_FORMAT_R32_FLOAT);
    const auto r16 = texture(device.Get(), DXGI_FORMAT_R16_FLOAT);
    const auto rgba = texture(device.Get(), DXGI_FORMAT_R16G16B16A16_FLOAT);
    checkCoverage(r32.Get());
    checkCoverage(r16.Get());
    checkAcquisition(r32.Get(), r16.Get());
    Harness host;
    need(!bind(host, snapshot(rgba.Get())), "unsupported linear-depth format refused");
    std::cout << "PASS: " << checks << " production title-depth capture, extent, acquisition and fallback checks\n";
}
catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
