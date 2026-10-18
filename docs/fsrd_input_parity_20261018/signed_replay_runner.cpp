// Real AMD RR replay of an NRD-bridge GAME_TRACE ROI: DIRECT_DIFFUSE + INDIRECT_SPECULAR, per-frame
// captured provider controls (ffxDispatchDescDenoiser suffix from motionVectorScale, 184 bytes) as the
// Python driver patched them for the ROI. Inputs are prepared (scaled, cropped) by the driver.
// job.txt: w h frames tuning(0/1) v1..v6 "dll" then 7 input records "path" dxgiFormat, then "diffOut" "specOut" "controls.bin"
#define NOMINMAX
#define _WINDOWS
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <vector>
#include <string>
#include <stdexcept>
#include <cstring>
#include "ffx_api_loader.h"
#include "dx12/ffx_api_dx12.h"
#include <upscalers/fsr31/FSRDRRInterop.h>
#define FSRD_RADIANCE_SCALE_TEST
#include <memory>
struct ResTrack_Dx12 {
    inline static std::vector<std::shared_ptr<void>> retained;
    static bool RetainComputeDispatch(ID3D12Device*,ID3D12GraphicsCommandList*,const std::shared_ptr<void>& lease)
    { retained.push_back(lease); return true; }
};
#include "shaders/fsrd_preprocess/FSRDRadianceScale_Dx12.h"
using Microsoft::WRL::ComPtr;
static_assert(offsetof(ffxDispatchDescDenoiser, motionVectorScale) == 264u);
static_assert(sizeof(ffxDispatchDescDenoiser) - offsetof(ffxDispatchDescDenoiser, motionVectorScale) == 184u);
void hr(HRESULT h, const char* s) { if (FAILED(h)) throw std::runtime_error(std::string(s) + " HRESULT=" + std::to_string(uint32_t(h))); }
void ff(ffxReturnCode_t h, const char* s) { if (h) throw std::runtime_error(std::string(s) + " FFX=" + std::to_string(h)); }
unsigned sdkErrors = 0;
void message(uint32_t type, const wchar_t* s) { if (type == FFX_API_MESSAGE_TYPE_ERROR) { ++sdkErrors; std::wcerr << L"SDK: " << s << L'\n'; } }
struct Tex { ComPtr<ID3D12Resource> tex, staging; D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; UINT64 size = 0; unsigned bpp = 0;
             DXGI_FORMAT format{}; std::ifstream input; D3D12_RESOURCE_STATES state{}; FfxApiResource api{}; };
int main(int argc, char** argv) try {
    std::cout << std::unitbuf;
    if (argc != 2) throw std::runtime_error("usage: rr_bridge job.txt");
    std::ifstream job(argv[1]);
    unsigned w, h, frames, tuning; float values[6]; std::string dllPath;
    job >> w >> h >> frames >> tuning; for (float& v : values) job >> v; job >> std::quoted(dllPath);
    if (!job) throw std::runtime_error("invalid header");
    ComPtr<ID3D12Debug> debug; hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)),"debug layer");
    debug->EnableDebugLayer();
    ComPtr<IDXGIFactory6> factory; hr(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "factory");
    ComPtr<IDXGIAdapter1> adapter; hr(factory->EnumAdapterByGpuPreference(0, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, IID_PPV_ARGS(&adapter)), "adapter");
    ComPtr<ID3D12Device> dev; hr(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&dev)), "device");
    ComPtr<ID3D12CommandQueue> queue; D3D12_COMMAND_QUEUE_DESC qd{}; hr(dev->CreateCommandQueue(&qd, IID_PPV_ARGS(&queue)), "queue");
    ComPtr<ID3D12CommandAllocator> alloc; hr(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&alloc)), "allocator");
    ComPtr<ID3D12GraphicsCommandList> cmd; hr(dev->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, alloc.Get(), nullptr, IID_PPV_ARGS(&cmd)), "list");
    hr(cmd->Close(), "close0");
    ComPtr<ID3D12Fence> fence; hr(dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "fence");
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    auto buffer = [&](UINT64 size, D3D12_HEAP_TYPE heap) {
        D3D12_HEAP_PROPERTIES hp{}; hp.Type = heap;
        D3D12_RESOURCE_DESC d{}; d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; d.Width = size; d.Height = 1; d.DepthOrArraySize = 1; d.MipLevels = 1; d.SampleDesc.Count = 1; d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> r; hr(dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, heap == D3D12_HEAP_TYPE_UPLOAD ? D3D12_RESOURCE_STATE_GENERIC_READ : D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&r)), "buffer"); return r; };
    auto barrier = [&](Tex& t, D3D12_RESOURCE_STATES next) {
        if (t.state == next) return; D3D12_RESOURCE_BARRIER b{}; b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition = {t.tex.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, t.state, next}; cmd->ResourceBarrier(1, &b); t.state = next; };
    // 0 depth, 1 motion, 2 normals, 3 spec albedo, 4 diff albedo, 5 diffuse in, 6 specular in, 7 diff out, 8 spec out
    std::vector<Tex> tex(9);
    for (unsigned i = 0; i < 9; ++i) {
        auto& t = tex[i]; int fmt = DXGI_FORMAT_R16G16B16A16_FLOAT; const bool in = i < 7;
        if (in) { std::string path; job >> std::quoted(path) >> fmt; t.input.open(path, std::ios::binary); if (!t.input) throw std::runtime_error("input " + path); }
        t.format = DXGI_FORMAT(fmt); t.bpp = fmt == DXGI_FORMAT_R16G16B16A16_FLOAT ? 8 : 4;
        D3D12_RESOURCE_DESC d{}; d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D; d.Width = w; d.Height = h; d.DepthOrArraySize = 1; d.MipLevels = 1; d.Format = t.format; d.SampleDesc.Count = 1;
        d.Flags = (!in || i >= 5) ? D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS : D3D12_RESOURCE_FLAG_NONE;
        D3D12_HEAP_PROPERTIES hp{}; hp.Type = D3D12_HEAP_TYPE_DEFAULT; t.state = in ? D3D12_RESOURCE_STATE_COPY_DEST : D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        hr(dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, t.state, nullptr, IID_PPV_ARGS(&t.tex)), "texture");
        dev->GetCopyableFootprints(&d, 0, 1, 0, &t.fp, nullptr, nullptr, &t.size);
        t.staging = buffer(t.size, in ? D3D12_HEAP_TYPE_UPLOAD : D3D12_HEAP_TYPE_READBACK);
        t.api.resource = t.tex.Get(); t.api.state = in ? FFX_API_RESOURCE_STATE_COMPUTE_READ : FFX_API_RESOURCE_STATE_UNORDERED_ACCESS;
        t.api.description = {FFX_API_RESOURCE_TYPE_TEXTURE2D, ffxApiGetSurfaceFormatDX12(t.format), w, h, 1, 1, 0, uint32_t(in ? FFX_API_RESOURCE_USAGE_READ_ONLY : FFX_API_RESOURCE_USAGE_UAV)};
        if (in) { t.input.seekg(0, std::ios::end); if (t.input.tellg() != std::streamoff(uint64_t(w) * h * t.bpp * frames)) throw std::runtime_error("input size " + std::to_string(i)); t.input.seekg(0); }
    }
    std::string diffOut, specOut, controlsPath; job >> std::quoted(diffOut) >> std::quoted(specOut) >> std::quoted(controlsPath);
    if (!job) throw std::runtime_error("invalid records");
    uint32_t diffuseScale=1,specularScale=1; job >> diffuseScale >> specularScale;
    if (!job) throw std::runtime_error("missing production scales");
    FSRDRadianceScaleDx12 scalePass;
    std::ofstream outD(diffOut, std::ios::binary), outS(specOut, std::ios::binary); std::ifstream controls(controlsPath, std::ios::binary);
    if (!outD || !outS || !controls) throw std::runtime_error("open outputs/controls");
    // The loader finds provider DLLs by name; let it search the loader's own directory.
    SetDllDirectoryW(std::filesystem::path(dllPath).parent_path().c_str());
    HMODULE module = LoadLibraryExW(std::filesystem::path(dllPath).c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!module) throw std::runtime_error("LoadLibrary " + std::to_string(GetLastError()));
    std::cout << "module" << std::endl;
    ffxFunctions api{}; ffxLoadFunctions(&api, module);
    std::cout << "functions " << (void*)api.CreateContext << ' ' << (void*)api.Configure << std::endl;
    struct ReplayGlobalDebug { ffxConfigureDescHeader header; uint64_t effectId; ffxApiMessage fpMessage; uint32_t debugLevel; };
                ReplayGlobalDebug logging{{7u, nullptr}, FFX_API_EFFECT_ID_DENOISER, message, FFX_API_CONFIGURE_GLOBALDEBUG_LEVEL_VERBOSE};
    ff(api.Configure(nullptr, &logging.header), "global debug configure");
    std::cout << "debug" << std::endl;
    // Select the RR provider by version exactly like the bridge (loader + override version).
    uint64_t count = 0; ffxQueryDescGetVersions versions{}; versions.header.type = FFX_API_QUERY_DESC_TYPE_GET_VERSIONS;
    versions.createDescType = FFX_API_EFFECT_ID_DENOISER; versions.device = dev.Get(); versions.outputCount = &count;
    ff(api.Query(nullptr, &versions.header), "version count");
    std::vector<uint64_t> ids(count); std::vector<const char*> names(count);
    versions.versionIds = ids.data(); versions.versionNames = names.data(); ff(api.Query(nullptr, &versions.header), "versions");
    uint64_t versionId = 0;
    for (uint64_t i = 0; i < count; ++i) {
        std::cout << "provider " << (names[i] ? names[i] : "?") << std::endl;
        const char* n = names[i]; if (!n) continue; while (*n && (*n < '0' || *n > '9')) ++n;
        unsigned a = 0, b = 0, p = 0;
        if (sscanf_s(n, "%u.%u.%u", &a, &b, &p) == 3 && a == FFX_DENOISER_VERSION_MAJOR && b == FFX_DENOISER_VERSION_MINOR && p == FFX_DENOISER_VERSION_PATCH) { versionId = ids[i]; break; }
    }
    if (!versionId) throw std::runtime_error("no matching RR provider");
    ffxOverrideVersion override{}; override.header.type = FFX_API_DESC_TYPE_OVERRIDE_VERSION; override.versionId = versionId;
    ffxCreateBackendDX12Desc backend{{FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12, &override.header}, dev.Get()};
    ffxCreateContextDescDenoiser create{{FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER, &backend.header}, FFX_DENOISER_VERSION, {w, h},
        FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE | FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR, 0, 0};
    std::cout << "loaded" << std::endl; ffxContext context = nullptr; ff(api.CreateContext(&context, &create.header, nullptr), "create RR"); std::cout << "created" << std::endl;
    if (tuning) {
        // AMD keys 1..6 in key order, exactly as the bridge's override mask 0x3f applies them.
        for (unsigned i = 0; i < 6; ++i) { ffxConfigureDescDenoiserKeyValue c{{FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE, nullptr}, uint64_t(i + 1), 1, values + i}; ff(api.Configure(&context, &c.header), "configure"); }
    }
    ffxDispatchDescDenoiserDirectDiffuse diffuse{}; diffuse.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE;
    diffuse.signal.input = tex[5].api; diffuse.signal.output = tex[7].api;
    ffxDispatchDescDenoiserIndirectSpecular specular{}; specular.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR;
    specular.signal.input = tex[6].api; specular.signal.output = tex[8].api; diffuse.header.pNext = &specular.header;
    ffxDispatchDescDenoiser dispatch{}; dispatch.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER; dispatch.header.pNext = &diffuse.header;
    dispatch.commandList = cmd.Get(); dispatch.linearDepth = tex[0].api; dispatch.motionVectors = tex[1].api; dispatch.normals = tex[2].api;
    dispatch.specularAlbedo = tex[3].api; dispatch.diffuseAlbedo = tex[4].api;
    for (unsigned frame = 0; frame < frames; ++frame) {
        ResTrack_Dx12::retained.clear();
        hr(alloc->Reset(), "reset alloc"); hr(cmd->Reset(alloc.Get(), nullptr), "reset list");
        for (unsigned i = 0; i < 7; ++i) {
            auto& t = tex[i]; barrier(t, D3D12_RESOURCE_STATE_COPY_DEST);
            char* mapped = nullptr; D3D12_RANGE empty{0, 0}; hr(t.staging->Map(0, &empty, reinterpret_cast<void**>(&mapped)), "map");
            for (unsigned y = 0; y < h; ++y) t.input.read(mapped + t.fp.Offset + y * t.fp.Footprint.RowPitch, size_t(w) * t.bpp);
            t.staging->Unmap(0, nullptr); if (!t.input) throw std::runtime_error("read");
            D3D12_TEXTURE_COPY_LOCATION src{}; src.pResource = t.staging.Get(); src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint = t.fp;
            D3D12_TEXTURE_COPY_LOCATION dst{}; dst.pResource = t.tex.Get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            cmd->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
            barrier(t, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        }
        controls.read(reinterpret_cast<char*>(&dispatch) + offsetof(ffxDispatchDescDenoiser, motionVectorScale), 184);
        if (!controls) throw std::runtime_error("controls read");
        if (frame == 0) dispatch.flags |= FFX_DENOISER_DISPATCH_RESET;
        if (frame == 0) std::cout << "dispatch0" << std::endl;
        {
            FSRDRadianceScaleDx12::Scope scope; std::string error;
            if (!scalePass.Before(dev.Get(),cmd.Get(),dispatch,{true,diffuseScale,specularScale},scope.work,error))
                throw std::runtime_error(error);
            ff(api.Dispatch(&context, &dispatch.header), "dispatch");
        }
        for (unsigned i = 7; i < 9; ++i) {
            auto& t = tex[i]; barrier(t, D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION src{}; src.pResource = t.tex.Get(); src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            D3D12_TEXTURE_COPY_LOCATION dst{}; dst.pResource = t.staging.Get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint = t.fp;
            cmd->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr); barrier(t, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        }
        hr(cmd->Close(), "close"); ID3D12CommandList* lists[] = {cmd.Get()}; queue->ExecuteCommandLists(1, lists);
        hr(queue->Signal(fence.Get(), frame + 1), "signal"); hr(fence->SetEventOnCompletion(frame + 1, event), "event");
        if (WaitForSingleObject(event, 60000) != WAIT_OBJECT_0) throw std::runtime_error("GPU timeout");
        hr(dev->GetDeviceRemovedReason(), "device removed");
        for (unsigned i = 7; i < 9; ++i) {
            auto& t = tex[i]; char* mapped = nullptr; hr(t.staging->Map(0, nullptr, reinterpret_cast<void**>(&mapped)), "readback");
            auto& out = i == 7 ? outD : outS;
            for (unsigned y = 0; y < h; ++y) out.write(mapped + t.fp.Offset + y * t.fp.Footprint.RowPitch, size_t(w) * 8);
            t.staging->Unmap(0, nullptr);
        }
    }
    ff(api.DestroyContext(&context, nullptr), "destroy"); CloseHandle(event); FreeLibrary(module);
    std::cout << "dispatches=" << frames << " sdk_errors=" << sdkErrors << '\n';
    ComPtr<ID3D12InfoQueue> info; hr(dev.As(&info),"info queue");
    unsigned errors=0,warnings=0;
    for(uint64_t i=0;i<info->GetNumStoredMessagesAllowedByRetrievalFilter();++i) {
        SIZE_T n=0;info->GetMessage(i,nullptr,&n);std::vector<uint8_t> bytes(n);
        auto* message=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());info->GetMessage(i,message,&n);
        if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR){++errors;std::cerr<<message->pDescription<<'\n';}
        else if(message->Severity==D3D12_MESSAGE_SEVERITY_WARNING){++warnings;std::cerr<<message->pDescription<<'\n';}
    }
    std::cout<<"d3d12_errors="<<errors<<" d3d12_warnings="<<warnings<<'\n';
    return sdkErrors||errors||warnings ? 2 : 0;
} catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
