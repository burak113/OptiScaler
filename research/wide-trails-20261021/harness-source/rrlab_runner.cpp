// RR Lab native runner: real AMD FSR Ray Regeneration replay of an NRD-bridge GAME_TRACE ROI (DIRECT_DIFFUSE +
// INDIRECT_SPECULAR), driven by rrlab/runner.py. job.txt: w h frames tuning(0/1) v1..v6 "loader dll", 7 input records
// "path" dxgiFormat, "diffOut" "specOut" "controls.bin" (184-byte ffxDispatchDescDenoiser suffix per frame).
// Environment: RR_SWAP_DIR (<sha256>.dxil replaces that PSO), RR_PSO_LOG (sha + markers), RR_TUNING_FILE (6 float32 per
// frame; keys 1..6 are reconfigured when they change, no reset), RR_STAB_FILE (legacy: 1 float32 per frame, key 2).
#define NOMINMAX
#define _WINDOWS
#include <windows.h>
#include <d3d12.h>
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
#include <algorithm>
#include <chrono>
#include "F:/OptiRevelations/OptiScaler-ffx-denoise-experimental/external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include/ffx_api_loader.h"
#include "F:/OptiRevelations/OptiScaler-ffx-denoise-experimental/external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include/dx12/ffx_api_dx12.h"
#include "F:/OptiRevelations/OptiScaler-ffx-denoise-experimental/external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h"
using Microsoft::WRL::ComPtr;

// ---- PSO swap hook (rr_swap): logs SHA-256 of every compute PSO the provider creates; when RR_SWAP_DIR holds
// <sha256>.dxil, that bytecode replaces the original. Only this process's own device vtable is redirected.
#include <bcrypt.h>
#include <map>
using CreatePSO = HRESULT(STDMETHODCALLTYPE*)(ID3D12Device*, const D3D12_COMPUTE_PIPELINE_STATE_DESC*, REFIID, void**);
static CreatePSO oldCreate = nullptr;
static std::filesystem::path swapDir; static std::ofstream psoLog; static unsigned swapped = 0;
static std::string sha256(const void* p, size_t n) {
    BCRYPT_ALG_HANDLE alg{}; BCRYPT_HASH_HANDLE hh{}; unsigned char d[32]{};
    BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0); BCryptCreateHash(alg, &hh, nullptr, 0, nullptr, 0, 0);
    BCryptHashData(hh, (PUCHAR)p, ULONG(n), 0); BCryptFinishHash(hh, d, 32, 0); BCryptDestroyHash(hh); BCryptCloseAlgorithmProvider(alg, 0);
    static const char* x = "0123456789abcdef"; std::string s; for (auto c : d) { s += x[c >> 4]; s += x[c & 15]; } return s; }
HRESULT STDMETHODCALLTYPE onCreate(ID3D12Device* d, const D3D12_COMPUTE_PIPELINE_STATE_DESC* desc, REFIID iid, void** result) {
    const std::string h = sha256(desc->CS.pShaderBytecode, desc->CS.BytecodeLength);
    std::vector<char> repl; bool use = false;
    if (!swapDir.empty()) { std::ifstream f(swapDir / (h + ".dxil"), std::ios::binary); if (f) { repl.assign(std::istreambuf_iterator<char>(f), {}); use = !repl.empty(); } }
    if (psoLog) psoLog << h << ' ' << desc->CS.BytecodeLength << (use ? " SWAPPED" : "") << '\n';
    if (!use) return oldCreate(d, desc, iid, result);
    D3D12_COMPUTE_PIPELINE_STATE_DESC copy = *desc; copy.CS.pShaderBytecode = repl.data(); copy.CS.BytecodeLength = repl.size();
    HRESULT r = oldCreate(d, &copy, iid, result);
    if (FAILED(r)) throw std::runtime_error("swapped PSO rejected " + h + " HRESULT=" + std::to_string(uint32_t(r)));
    ++swapped; return r; }
struct OwnVtable { void*** object; void** original; void* copy[160];
    explicit OwnVtable(void* p) : object(reinterpret_cast<void***>(p)), original(*object) { std::memcpy(copy, original, sizeof(copy)); *object = copy; }
    ~OwnVtable() { *object = original; } };
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
    // Optional task-23 measurement; ordinary job replay and its executable remain unchanged.
    const std::string costMode=std::getenv("RR_COST23")?std::getenv("RR_COST23"):"";
    const bool costOnly=!costMode.empty(),splitCost=costMode=="split2_32";
    if(costOnly&&(costMode!="joint34"&&!splitCost))throw std::runtime_error("invalid RR_COST23 mode");
    if(costOnly&&(frames!=1||!tuning||std::getenv("RR_TUNING_FILE")||std::getenv("RR_STAB_FILE")||std::getenv("RR_SWAP_DIR")))
        throw std::runtime_error("cost23 requires one frozen input, explicit fixed tuning and no hooks/patches");
    constexpr unsigned CostWarm=16,CostSamples=64;
    std::vector<double> costGpu,costCpu;
    auto quantile=[](std::vector<double> a,double p){std::sort(a.begin(),a.end());const double q=(a.size()-1)*p;
        const size_t i=size_t(q),j=std::min(i+1,a.size()-1);return a[i]+(a[j]-a[i])*(q-i);};
    ComPtr<IDXGIFactory6> factory; hr(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "factory");
    ComPtr<IDXGIAdapter1> adapter; hr(factory->EnumAdapterByGpuPreference(0, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, IID_PPV_ARGS(&adapter)), "adapter");
    ComPtr<ID3D12Device> dev; hr(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&dev)), "device");
    if (const char* s = std::getenv("RR_SWAP_DIR")) swapDir = s;
    if (const char* s = std::getenv("RR_PSO_LOG")) psoLog.open(s, std::ios::app);
    OwnVtable deviceHook(dev.Get()); oldCreate = reinterpret_cast<CreatePSO>(deviceHook.copy[11]); deviceHook.copy[11] = reinterpret_cast<void*>(&onCreate);
    ComPtr<ID3D12CommandQueue> queue; D3D12_COMMAND_QUEUE_DESC qd{}; hr(dev->CreateCommandQueue(&qd, IID_PPV_ARGS(&queue)), "queue");
    ComPtr<ID3D12CommandAllocator> alloc; hr(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&alloc)), "allocator");
    ComPtr<ID3D12GraphicsCommandList> cmd; hr(dev->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, alloc.Get(), nullptr, IID_PPV_ARGS(&cmd)), "list");
    hr(cmd->Close(), "close0");
    ComPtr<ID3D12Fence> fence; hr(dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "fence");
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    ComPtr<IDXGIAdapter3> memoryAdapter;adapter.As(&memoryAdapter);uint64_t sampledLocalMaximum=0;
    auto memorySample=[&](const char* stage){if(!costOnly||!memoryAdapter)return;DXGI_QUERY_VIDEO_MEMORY_INFO m{};
        hr(memoryAdapter->QueryVideoMemoryInfo(0,DXGI_MEMORY_SEGMENT_GROUP_LOCAL,&m),"cost23 DXGI memory");
        sampledLocalMaximum=std::max(sampledLocalMaximum,m.CurrentUsage);
        std::cout<<"cost23_dxgi stage="<<stage<<" budget="<<m.Budget<<" current="<<m.CurrentUsage<<'\n';};
    memorySample("before_resources");
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
        d.Flags = in ? D3D12_RESOURCE_FLAG_NONE : D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES hp{}; hp.Type = D3D12_HEAP_TYPE_DEFAULT; t.state = in ? D3D12_RESOURCE_STATE_COPY_DEST : D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        hr(dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, t.state, nullptr, IID_PPV_ARGS(&t.tex)), "texture");
        dev->GetCopyableFootprints(&d, 0, 1, 0, &t.fp, nullptr, nullptr, &t.size);
        if(in||!costOnly)t.staging = buffer(t.size, in ? D3D12_HEAP_TYPE_UPLOAD : D3D12_HEAP_TYPE_READBACK);
        t.api.resource = t.tex.Get(); t.api.state = in ? FFX_API_RESOURCE_STATE_COMPUTE_READ : FFX_API_RESOURCE_STATE_UNORDERED_ACCESS;
        t.api.description = {FFX_API_RESOURCE_TYPE_TEXTURE2D, ffxApiGetSurfaceFormatDX12(t.format), w, h, 1, 1, 0, uint32_t(in ? FFX_API_RESOURCE_USAGE_READ_ONLY : FFX_API_RESOURCE_USAGE_UAV)};
        if (in) { t.input.seekg(0, std::ios::end); if (t.input.tellg() != std::streamoff(uint64_t(w) * h * t.bpp * frames)) throw std::runtime_error("input size " + std::to_string(i)); t.input.seekg(0); }
    }
    ComPtr<ID3D12QueryHeap> costQueries;ComPtr<ID3D12Resource> costReadback;uint64_t costFrequency=0;
    if(costOnly){D3D12_QUERY_HEAP_DESC d{};d.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;d.Count=2;
        hr(dev->CreateQueryHeap(&d,IID_PPV_ARGS(&costQueries)),"cost23 timestamp heap");costReadback=buffer(16,D3D12_HEAP_TYPE_READBACK);
        hr(queue->GetTimestampFrequency(&costFrequency),"cost23 frequency");
        std::cout<<"cost23_scope mode="<<costMode<<" width="<<w<<" height="<<h<<" warm="<<CostWarm<<" samples="<<CostSamples
            <<" timestamp_frequency="<<costFrequency<<" fixed_realization=1 output_readbacks=0\n";}
    std::string diffOut, specOut, controlsPath; job >> std::quoted(diffOut) >> std::quoted(specOut) >> std::quoted(controlsPath);
    if (!job) throw std::runtime_error("invalid records");
    std::ofstream outD,outS;std::ifstream controls(controlsPath,std::ios::binary);
    if(!costOnly){outD.open(diffOut,std::ios::binary);outS.open(specOut,std::ios::binary);}
    if ((!costOnly&&(!outD||!outS)) || !controls) throw std::runtime_error("open outputs/controls");
    // The loader finds provider DLLs by name; let it search the loader's own directory.
    SetDllDirectoryW(std::filesystem::path(dllPath).parent_path().c_str());
    HMODULE module = LoadLibraryExW(std::filesystem::path(dllPath).c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!module) throw std::runtime_error("LoadLibrary " + std::to_string(GetLastError()));
    std::cout << "module" << std::endl;
    ffxFunctions api{}; ffxLoadFunctions(&api, module);
    std::cout << "functions " << (void*)api.CreateContext << ' ' << (void*)api.Configure << std::endl;
    ffxConfigureDescGlobalDebug logging{{FFX_API_CONFIGURE_DESC_TYPE_GLOBALDEBUG, nullptr}, FFX_API_EFFECT_ID_DENOISER, message, FFX_API_CONFIGURE_GLOBALDEBUG_LEVEL_VERBOSE};
    api.Configure(nullptr, &logging.header);
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
    if(splitCost)create.signalFlags=FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE;
    std::cout << "loaded" << std::endl; ffxContext context = nullptr; ff(api.CreateContext(&context, &create.header, nullptr), "create RR"); std::cout << "created" << std::endl; if (psoLog) psoLog << "# context created" << std::endl;
    ffxContext specContext=nullptr;
    auto contextMemory=[&](ffxContext* ctx,uint32_t flags,const char* stage){
        FfxApiEffectMemoryUsage usage{};ffxQueryDescDenoiserGetGPUMemoryUsage q{};
        q.header.type=FFX_API_QUERY_DESC_TYPE_DENOISER_GPU_MEMORY_USAGE;q.device=dev.Get();q.maxRenderSize={w,h};
        q.signalFlags=flags;q.gpuMemoryUsage=&usage;ff(api.Query(ctx,&q.header),"cost23 actual context memory");
        // Some1.2 provider counters underflow while Query returns OK; retain raw words, mark unavailable.
        const bool plausible=usage.totalUsageInBytes<(1ull<<40)&&usage.aliasableUsageInBytes<=usage.totalUsageInBytes;
        std::cout<<"cost23_memory stage="<<stage<<" flags="<<flags<<" total_bytes="<<usage.totalUsageInBytes
            <<" aliasable_bytes="<<usage.aliasableUsageInBytes<<" valid="<<plausible<<'\n';return usage;};
    if(costOnly){contextMemory(&context,create.signalFlags,"created_first");memorySample("created_first");}
    if(splitCost){create.signalFlags=FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR;
        ff(api.CreateContext(&specContext,&create.header,nullptr),"create RR single specular");
        contextMemory(&specContext,create.signalFlags,"created_second");memorySample("created_pair");}
    if (tuning) {
        // AMD keys 1..6 in key order, exactly as the bridge's override mask 0x3f applies them.
        for (unsigned i = 0; i < 6; ++i) { ffxConfigureDescDenoiserKeyValue c{{FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE, nullptr}, uint64_t(i + 1), 1, values + i}; ff(api.Configure(&context, &c.header), "configure");
            if(splitCost)ff(api.Configure(&specContext,&c.header),"configure single specular");
            if(costOnly)std::cout<<"cost23_tuning key="<<i+1<<" value="<<values[i]<<'\n'; }
    }
    ffxDispatchDescDenoiserDirectDiffuse diffuse{}; diffuse.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE;
    diffuse.signal.input = tex[5].api; diffuse.signal.output = tex[7].api;
    ffxDispatchDescDenoiserIndirectSpecular specular{}; specular.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR;
    specular.signal.input = tex[6].api; specular.signal.output = tex[8].api; diffuse.header.pNext = &specular.header;
    ffxDispatchDescDenoiser dispatch{}; dispatch.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER; dispatch.header.pNext = &diffuse.header;
    dispatch.commandList = cmd.Get(); dispatch.linearDepth = tex[0].api; dispatch.motionVectors = tex[1].api; dispatch.normals = tex[2].api;
    dispatch.specularAlbedo = tex[3].api; dispatch.diffuseAlbedo = tex[4].api;
    std::vector<float> stab; if (const char* p = std::getenv("RR_STAB_FILE")) { std::ifstream f(p, std::ios::binary); float v; while (f.read(reinterpret_cast<char*>(&v), 4)) stab.push_back(v); }
    float lastStab = tuning ? values[1] : -1.0f;
    std::vector<float> perFrame; if (const char* p = std::getenv("RR_TUNING_FILE")) { std::ifstream f(p, std::ios::binary); float v; while (f.read(reinterpret_cast<char*>(&v), 4)) perFrame.push_back(v); }
    float lastTuning[6]; for (unsigned k = 0; k < 6; ++k) lastTuning[k] = tuning ? values[k] : -1.0f;
    for (unsigned frame = 0; frame < (costOnly?CostWarm+CostSamples:frames); ++frame) {
        if (size_t(frame) * 6 + 6 <= perFrame.size())
            for (unsigned k = 0; k < 6; ++k) {
                float v = perFrame[size_t(frame) * 6 + k];
                if (v == lastTuning[k]) continue;
                ffxConfigureDescDenoiserKeyValue c{{FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE, nullptr}, uint64_t(k + 1), 1, &v};
                ff(api.Configure(&context, &c.header), "configure per-frame tuning"); lastTuning[k] = v;
            }
        if (frame < stab.size() && stab[frame] != lastStab) {
            ffxConfigureDescDenoiserKeyValue c{{FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE, nullptr}, 2u, 1, &stab[frame]};
            ff(api.Configure(&context, &c.header), "configure stability"); lastStab = stab[frame];
        }
        hr(alloc->Reset(), "reset alloc"); hr(cmd->Reset(alloc.Get(), nullptr), "reset list");
        if(!costOnly||frame==0)for (unsigned i = 0; i < 7; ++i) {
            auto& t = tex[i]; barrier(t, D3D12_RESOURCE_STATE_COPY_DEST);
            char* mapped = nullptr; D3D12_RANGE empty{0, 0}; hr(t.staging->Map(0, &empty, reinterpret_cast<void**>(&mapped)), "map");
            for (unsigned y = 0; y < h; ++y) t.input.read(mapped + t.fp.Offset + y * t.fp.Footprint.RowPitch, size_t(w) * t.bpp);
            t.staging->Unmap(0, nullptr); if (!t.input) throw std::runtime_error("read");
            D3D12_TEXTURE_COPY_LOCATION src{}; src.pResource = t.staging.Get(); src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint = t.fp;
            D3D12_TEXTURE_COPY_LOCATION dst{}; dst.pResource = t.tex.Get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            cmd->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
            barrier(t, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        }
        if(!costOnly||frame==0)controls.read(reinterpret_cast<char*>(&dispatch) + offsetof(ffxDispatchDescDenoiser, motionVectorScale), 184);
        if(costOnly){dispatch.frameIndex=frame;dispatch.flags&=~FFX_DENOISER_DISPATCH_RESET;}
        if (!controls) throw std::runtime_error("controls read");
        if (frame == 0) dispatch.flags |= FFX_DENOISER_DISPATCH_RESET;
        if (frame == 0) std::cout << "dispatch0" << std::endl;
        if (psoLog) psoLog << "# dispatch " << frame << std::endl;
        if(costOnly)cmd->EndQuery(costQueries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        const auto recordStart=costOnly?std::chrono::steady_clock::now():std::chrono::steady_clock::time_point{};
        if(splitCost){diffuse.header.pNext=nullptr;dispatch.header.pNext=&diffuse.header;
            ff(api.Dispatch(&context,&dispatch.header),"dispatch single diffuse");dispatch.header.pNext=&specular.header;
            ff(api.Dispatch(&specContext,&dispatch.header),"dispatch single specular");}
        else ff(api.Dispatch(&context, &dispatch.header), "dispatch");
        const double recordUs=costOnly?std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-recordStart).count():0;
        if(costOnly){cmd->EndQuery(costQueries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
            cmd->ResolveQueryData(costQueries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,costReadback.Get(),0);}
        if(!costOnly)for (unsigned i = 7; i < 9; ++i) {
            auto& t = tex[i]; barrier(t, D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION src{}; src.pResource = t.tex.Get(); src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            D3D12_TEXTURE_COPY_LOCATION dst{}; dst.pResource = t.staging.Get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint = t.fp;
            cmd->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr); barrier(t, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        }
        hr(cmd->Close(), "close"); ID3D12CommandList* lists[] = {cmd.Get()}; queue->ExecuteCommandLists(1, lists);
        hr(queue->Signal(fence.Get(), frame + 1), "signal"); hr(fence->SetEventOnCompletion(frame + 1, event), "event");
        if (WaitForSingleObject(event, 60000) != WAIT_OBJECT_0) throw std::runtime_error("GPU timeout");
        hr(dev->GetDeviceRemovedReason(), "device removed");
        if(costOnly){uint64_t* ticks=nullptr;D3D12_RANGE read{0,16};hr(costReadback->Map(0,&read,reinterpret_cast<void**>(&ticks)),"cost23 timestamp readback");
            const double us=double(ticks[1]-ticks[0])*1e6/double(costFrequency);D3D12_RANGE empty{0,0};costReadback->Unmap(0,&empty);
            if(frame>=CostWarm){costGpu.push_back(us);costCpu.push_back(recordUs);}
            std::cout<<"cost23_sample frame="<<frame<<" reset="<<((dispatch.flags&FFX_DENOISER_DISPATCH_RESET)?1:0)
                <<" gpu_us="<<us<<" cpu_record_us="<<recordUs<<'\n';
            memorySample("completed_frame");continue;}
        for (unsigned i = 7; i < 9; ++i) {
            auto& t = tex[i]; char* mapped = nullptr; hr(t.staging->Map(0, nullptr, reinterpret_cast<void**>(&mapped)), "readback");
            auto& out = i == 7 ? outD : outS;
            for (unsigned y = 0; y < h; ++y) out.write(mapped + t.fp.Offset + y * t.fp.Footprint.RowPitch, size_t(w) * 8);
            t.staging->Unmap(0, nullptr);
        }
    }
    if(costOnly){contextMemory(&context,splitCost?2u:34u,"completed_first");if(splitCost)contextMemory(&specContext,32u,"completed_second");
        std::cout<<"cost23_summary mode="<<costMode<<" width="<<w<<" height="<<h<<" samples="<<costGpu.size()
            <<" gpu_us_p50="<<quantile(costGpu,.5)<<" gpu_us_p90="<<quantile(costGpu,.9)
            <<" cpu_record_us_p50="<<quantile(costCpu,.5)<<" cpu_record_us_p90="<<quantile(costCpu,.9)
            <<" sampled_local_max_bytes="<<sampledLocalMaximum<<'\n';}
    if(specContext)ff(api.DestroyContext(&specContext,nullptr),"destroy single specular");
    ff(api.DestroyContext(&context, nullptr), "destroy"); CloseHandle(event); FreeLibrary(module);
    std::cout << "dispatches=" << (costOnly?(CostWarm+CostSamples)*(splitCost?2u:1u):frames) << " swapped=" << swapped << " sdk_errors=" << sdkErrors << '\n';
    return sdkErrors ? 2 : 0;
} catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
