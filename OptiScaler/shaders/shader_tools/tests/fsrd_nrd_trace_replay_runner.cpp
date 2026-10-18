// Offline, explicit-provider RR replay. No native NRD output, title hooks,
// reconstruction of guides, or quality oracle. Paired observations only.
#define NOMINMAX
#define _WINDOWS
#include <windows.h>
#include <bcrypt.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <DirectXPackedVector.h>
#include <json.hpp>
#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <climits>
#include <cmath>
#include <cstddef>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>
#include "__FFX_LOADER__"
#include "__FFX_DX12__"
#include "__FFX_DENOISER__"
using Microsoft::WRL::ComPtr;
using Json=nlohmann::json;
static_assert(sizeof(ffxDispatchDescDenoiser)==448);
static_assert(offsetof(ffxDispatchDescDenoiser,motionVectorScale)==264);
static_assert(sizeof(FfxApiDenoiserSignal)==104);
static_assert(FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE==2 && FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR==32);
void Require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
void Hr(HRESULT value,const char* message){if(FAILED(value))throw std::runtime_error(std::string(message)+" HRESULT="+std::to_string(uint32_t(value)));}
void Ff(ffxReturnCode_t value,const char* message){if(value)throw std::runtime_error(std::string(message)+" FFX="+std::to_string(value));}
std::filesystem::path Path(const std::string& value){return std::filesystem::u8path(value);}
struct Handle
{
    HANDLE value=INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE h=INVALID_HANDLE_VALUE):value(h){}
    ~Handle(){if(value!=INVALID_HANDLE_VALUE&&value)CloseHandle(value);}
    Handle(const Handle&)=delete;
};
struct Hash
{
    BCRYPT_ALG_HANDLE algorithm=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;
    std::vector<uint8_t> object;
    Hash()
    {
        Require(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0,"open SHA-256");
        DWORD length=0,received=0;
        Require(BCryptGetProperty(algorithm,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&length),4,&received,0)>=0,"SHA object length");
        object.resize(length);Require(BCryptCreateHash(algorithm,&hash,object.data(),length,nullptr,0,0)>=0,"create SHA-256");
    }
    ~Hash(){if(hash)BCryptDestroyHash(hash);if(algorithm)BCryptCloseAlgorithmProvider(algorithm,0);}
    void Add(const void* bytes,size_t count)
    {Require(count<=ULONG_MAX&&BCryptHashData(hash,const_cast<PUCHAR>(static_cast<const uint8_t*>(bytes)),ULONG(count),0)>=0,"SHA update");}
    std::string Finish()
    {
        std::array<uint8_t,32> result{};Require(BCryptFinishHash(hash,result.data(),DWORD(result.size()),0)>=0,"SHA finish");
        constexpr char hex[]="0123456789abcdef";std::string text(64,'0');
        for(size_t i=0;i<result.size();++i){text[2*i]=hex[result[i]>>4];text[2*i+1]=hex[result[i]&15];}return text;
    }
};
struct FrozenFile
{
    Handle file;uint64_t size=0;
    explicit FrozenFile(const std::filesystem::path& path):file(CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr))
    {
        Require(file.value!=INVALID_HANDLE_VALUE,"open immutable input file");LARGE_INTEGER bytes{};
        Require(GetFileSizeEx(file.value,&bytes)&&bytes.QuadPart>=0,"input length");size=uint64_t(bytes.QuadPart);
    }
    void Rewind(){LARGE_INTEGER zero{};Require(SetFilePointerEx(file.value,zero,nullptr,FILE_BEGIN)!=FALSE,"rewind input");}
    void Read(void* destination,size_t bytes)
    {
        Require(bytes<=MAXDWORD,"bounded input read");DWORD got=0;
        Require(ReadFile(file.value,destination,DWORD(bytes),&got,nullptr)&&got==bytes,"input short read");
    }
    std::string Digest()
    {
        Rewind();Hash hash;std::array<uint8_t,65536> bytes{};uint64_t remaining=size;
        while(remaining){const auto count=size_t(std::min<uint64_t>(remaining,bytes.size()));Read(bytes.data(),count);hash.Add(bytes.data(),count);remaining-=count;}
        Rewind();return hash.Finish();
    }
    std::vector<uint8_t> Payload(const Json& row,uint64_t expected)
    {
        Require(size==expected&&row.at("bytes").get<uint64_t>()==expected,"typed payload length mismatch");
        Require(expected<=256ull*1024*1024,"one payload exceeds frame budget");std::vector<uint8_t> bytes(static_cast<size_t>(expected),uint8_t{});
        Read(bytes.data(),bytes.size());Hash hash;hash.Add(bytes.data(),bytes.size());
        Require(hash.Finish()==row.at("sha256").get<std::string>(),"payload SHA-256 changed before native use");return bytes;
    }
};
bool SameFile(HANDLE left,HANDLE right)
{
    BY_HANDLE_FILE_INFORMATION a{},b{};Require(GetFileInformationByHandle(left,&a)&&GetFileInformationByHandle(right,&b),"file identity unavailable");
    return a.dwVolumeSerialNumber==b.dwVolumeSerialNumber&&a.nFileIndexHigh==b.nFileIndexHigh&&a.nFileIndexLow==b.nFileIndexLow;
}
std::atomic<unsigned> sdkErrors{0},sdkWarnings{0};
void SdkMessage(uint32_t kind,const wchar_t* text)
{
    if(kind==FFX_API_MESSAGE_TYPE_ERROR)++sdkErrors;else ++sdkWarnings;
    std::wcerr<<L"SDK: "<<(text?text:L"<null>")<<L'\n';
}
struct Provider
{
    FrozenFile frozen;HMODULE module=nullptr;ffxFunctions api{};ffxContext context=nullptr;
    // The API may retain the creation descriptor chain until DestroyContext.
    ffxOverrideVersion selected{};ffxCreateBackendDX12Desc backend{};ffxCreateContextDescDenoiser create{};
    explicit Provider(const Json& job):frozen(Path(job.at("provider").get<std::string>()))
    {
        Require(frozen.Digest()==job.at("provider_sha256").get<std::string>(),"explicit provider SHA-256 mismatch");
        module=LoadLibraryExW(Path(job.at("provider").get<std::string>()).c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
        Require(module!=nullptr,"load explicit provider");
        std::array<wchar_t,32768> actual{};const DWORD count=GetModuleFileNameW(module,actual.data(),DWORD(actual.size()));
        Require(count>0&&count<actual.size(),"loaded module path unavailable");FrozenFile loaded(std::filesystem::path(actual.data()));
        Require(SameFile(frozen.file.value,loaded.file.value),"loaded module is not frozen explicit provider file");
        Require(loaded.Digest()==job.at("provider_sha256").get<std::string>(),"loaded provider disk bytes differ");
        ffxLoadFunctions(&api,module);
        Require(api.CreateContext&&api.DestroyContext&&api.Configure&&api.Dispatch&&api.Query,"provider exports missing");
    }
    ~Provider(){if(context)api.DestroyContext(&context,nullptr);if(module)FreeLibrary(module);}
};
struct Texture
{
    ComPtr<ID3D12Resource> resource,transfer;D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    uint64_t bytes=0;uint32_t bpp=0;D3D12_RESOURCE_STATES state=D3D12_RESOURCE_STATE_COPY_DEST;FfxApiResource api{};
};
struct Device
{
    ComPtr<ID3D12Device> device;ComPtr<ID3D12InfoQueue> info;
    ComPtr<ID3D12CommandQueue> queue;ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;ComPtr<ID3D12Fence> fence;
    Handle event{CreateEventW(nullptr,FALSE,FALSE,nullptr)};std::string adapter;uint64_t signaled=0;
    unsigned errors=0,warnings=0;
    Device()
    {
        ComPtr<ID3D12Debug> debug;Hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)),"D3D12 debug layer required");debug->EnableDebugLayer();
        ComPtr<IDXGIFactory6> factory;Hr(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)),"DXGI factory");
        ComPtr<IDXGIAdapter1> gpu;Hr(factory->EnumAdapterByGpuPreference(0,DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,IID_PPV_ARGS(&gpu)),"hardware adapter");
        DXGI_ADAPTER_DESC1 desc{};Hr(gpu->GetDesc1(&desc),"adapter description");Require(!(desc.Flags&DXGI_ADAPTER_FLAG_SOFTWARE),"hardware RR required; WARP forbidden");
        std::array<char,1024> name{};WideCharToMultiByte(CP_UTF8,0,desc.Description,-1,name.data(),int(name.size()),nullptr,nullptr);adapter=name.data();
        Hr(D3D12CreateDevice(gpu.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)),"D3D12 hardware device");Hr(device.As(&info),"debug info queue");
        D3D12_COMMAND_QUEUE_DESC q{};Hr(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)),"queue");
        Hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)),"allocator");
        Hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)),"command list");Hr(list->Close(),"initial close");
        Hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"fence");Require(event.value!=nullptr,"fence event");
    }
    ComPtr<ID3D12Resource> Buffer(uint64_t bytes,D3D12_HEAP_TYPE type)
    {
        D3D12_HEAP_PROPERTIES heap{};heap.Type=type;D3D12_RESOURCE_DESC desc{};
        desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;desc.Width=bytes;desc.Height=desc.DepthOrArraySize=desc.MipLevels=1;
        desc.SampleDesc.Count=1;desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;ComPtr<ID3D12Resource> result;
        Hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,type==D3D12_HEAP_TYPE_UPLOAD?D3D12_RESOURCE_STATE_GENERIC_READ:D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&result)),"transfer buffer");return result;
    }
    Texture Create(uint32_t width,uint32_t height,DXGI_FORMAT format,bool output,D3D12_RESOURCE_FLAGS inputFlags=D3D12_RESOURCE_FLAG_NONE)
    {
        Texture t;t.bpp=format==DXGI_FORMAT_R16G16B16A16_FLOAT?8:4;
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;D3D12_RESOURCE_DESC desc{};
        desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;desc.Width=width;desc.Height=height;desc.DepthOrArraySize=desc.MipLevels=1;
        desc.SampleDesc.Count=1;desc.Format=format;desc.Flags=output?D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS:inputFlags;
        t.state=output?D3D12_RESOURCE_STATE_UNORDERED_ACCESS:D3D12_RESOURCE_STATE_COPY_DEST;
        Hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,t.state,nullptr,IID_PPV_ARGS(&t.resource)),"texture");
        device->GetCopyableFootprints(&desc,0,1,0,&t.footprint,nullptr,nullptr,&t.bytes);
        t.transfer=Buffer(t.bytes,output?D3D12_HEAP_TYPE_READBACK:D3D12_HEAP_TYPE_UPLOAD);
        t.api=ffxApiGetResourceDX12(t.resource.Get(),output?FFX_API_RESOURCE_STATE_UNORDERED_ACCESS:FFX_API_RESOURCE_STATE_COMPUTE_READ);return t;
    }
    void Barrier(Texture& t,D3D12_RESOURCE_STATES next)
    {
        if(t.state==next)return;D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition={t.resource.Get(),0,t.state,next};list->ResourceBarrier(1,&barrier);t.state=next;
    }
    void Upload(Texture& t,const Json& row,uint32_t width,uint32_t height,float radianceScale=1)
    {
        FrozenFile input(Path(row.at("file").get<std::string>()));const uint64_t tight=uint64_t(width)*height*t.bpp;
        Require(input.size==tight&&row.at("bytes").get<uint64_t>()==tight,"input typed length changed");
        Barrier(t,D3D12_RESOURCE_STATE_COPY_DEST);uint8_t* mapped=nullptr;D3D12_RANGE empty{};
        Hr(t.transfer->Map(0,&empty,reinterpret_cast<void**>(&mapped)),"upload map");Hash hash;
        try
        {
            for(uint32_t y=0;y<height;++y){auto* dst=mapped+t.footprint.Offset+uint64_t(y)*t.footprint.Footprint.RowPitch;
                input.Read(dst,size_t(width)*t.bpp);hash.Add(dst,size_t(width)*t.bpp);
                if(radianceScale!=1) for(uint32_t x=0;x<width;++x) for(uint32_t c=0;c<3;++c)
                {
                    uint16_t word;memcpy(&word,dst+x*8+c*2,2);
                    const float value=DirectX::PackedVector::XMConvertHalfToFloat(word)*radianceScale;
                    word=DirectX::PackedVector::XMConvertFloatToHalf(value>65504.f?65504.f:value);
                    memcpy(dst+x*8+c*2,&word,2);
                }}
        }
        catch(...){t.transfer->Unmap(0,nullptr);throw;}
        t.transfer->Unmap(0,nullptr);Require(hash.Finish()==row.at("sha256").get<std::string>(),"input SHA changed before dispatch");
        D3D12_TEXTURE_COPY_LOCATION src{},dst{};src.pResource=t.transfer.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=t.footprint;
        dst.pResource=t.resource.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
        Barrier(t,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    }
    void Readback(Texture& t)
    {
        Barrier(t,D3D12_RESOURCE_STATE_COPY_SOURCE);D3D12_TEXTURE_COPY_LOCATION src{},dst{};
        src.pResource=t.resource.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.pResource=t.transfer.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=t.footprint;
        list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);Barrier(t,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    }
    void Submit()
    {
        Hr(list->Close(),"close list");ID3D12CommandList* commands[]={list.Get()};queue->ExecuteCommandLists(1,commands);
        ++signaled;Hr(queue->Signal(fence.Get(),signaled),"signal");Hr(fence->SetEventOnCompletion(signaled,event.value),"completion event");
        Require(WaitForSingleObject(event.value,60000)==WAIT_OBJECT_0,"bounded replay fence timeout");
        Require(fence->GetCompletedValue()!=UINT64_MAX&&fence->GetCompletedValue()>=signaled,"device-removed/incomplete fence");
        Hr(device->GetDeviceRemovedReason(),"device removed");
        for(uint64_t i=0;i<info->GetNumStoredMessages();++i)
        {
            SIZE_T size=0;Hr(info->GetMessage(i,nullptr,&size),"message size");std::vector<uint8_t> bytes(size);
            auto* m=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());Hr(info->GetMessage(i,m,&size),"message");
            if(m->Severity<=D3D12_MESSAGE_SEVERITY_ERROR){++errors;std::cerr<<m->pDescription<<'\n';}
            else if(m->Severity==D3D12_MESSAGE_SEVERITY_WARNING){++warnings;std::cerr<<m->pDescription<<'\n';}
        }
        info->ClearStoredMessages();Require(errors==0&&sdkErrors==0,"native replay validation error");
    }
};
struct ErrorMetrics
{
    long double square=0,chromaSquare=0,temporalSquare=0,referenceSquare=0,replayedSquare=0;
    uint64_t pixels=0,temporalPixels=0,nonfinite=0;double maximum=0;
    Json Read(Texture& t,const Json& row,uint32_t width,uint32_t height,std::vector<float>& previous,float radianceScale=1)
    {
        FrozenFile file(Path(row.at("file").get<std::string>()));auto captured=file.Payload(row,uint64_t(width)*height*8);
        const bool hasPrevious=!previous.empty();if(!hasPrevious)previous.resize(size_t(width)*height*3);
        uint8_t* mapped=nullptr;D3D12_RANGE range{SIZE_T(t.footprint.Offset),SIZE_T(t.bytes)};
        Hr(t.transfer->Map(0,&range,reinterpret_cast<void**>(&mapped)),"output map");
        for(uint32_t y=0;y<height;++y)for(uint32_t x=0;x<width;++x)
        {
            const uint8_t* replay=mapped+t.footprint.Offset+uint64_t(y)*t.footprint.Footprint.RowPitch+8*x;
            const uint8_t* reference=captured.data()+(uint64_t(y)*width+x)*8;float delta[3]{},av[3]{},bv[3]{};bool finite=true;
            for(unsigned c=0;c<3;++c){uint16_t a=0,b=0;memcpy(&a,replay+2*c,2);memcpy(&b,reference+2*c,2);
                av[c]=DirectX::PackedVector::XMConvertHalfToFloat(DirectX::PackedVector::XMConvertFloatToHalf(
                    DirectX::PackedVector::XMConvertHalfToFloat(a)/radianceScale));
                bv[c]=DirectX::PackedVector::XMConvertHalfToFloat(b);
                finite=finite&&std::isfinite(av[c])&&std::isfinite(bv[c]);delta[c]=av[c]-bv[c];}
            if(!finite){++nonfinite;continue;}++pixels;
            const double yDelta=.2126*delta[0]+.7152*delta[1]+.0722*delta[2];
            chromaSquare+=(delta[0]-yDelta)*(delta[0]-yDelta)+(delta[2]-yDelta)*(delta[2]-yDelta);
            for(unsigned c=0;c<3;++c){const size_t index=(size_t(y)*width+x)*3+c;square+=double(delta[c])*delta[c];
                referenceSquare+=double(bv[c])*bv[c];replayedSquare+=double(av[c])*av[c];maximum=std::max(maximum,double(std::abs(delta[c])));
                if(hasPrevious)temporalSquare+=double(delta[c]-previous[index])*(delta[c]-previous[index]);previous[index]=delta[c];}
            if(hasPrevious)++temporalPixels;
        }
        D3D12_RANGE empty{};t.transfer->Unmap(0,&empty);
        const double rmse=pixels?std::sqrt(double(square/(3*pixels))):0,referenceRms=pixels?std::sqrt(double(referenceSquare/(3*pixels))):0;
        return {{"finite_pixels",pixels},{"nonfinite_pixels",nonfinite},{"rgb_rmse",rmse},
            {"captured_rgb_rms",referenceRms},{"replayed_rgb_rms",pixels?std::sqrt(double(replayedSquare/(3*pixels))):0},
            {"rgb_normalized_rmse",rmse/std::max(referenceRms,1e-6)},
            {"maximum_absolute_rgb_error",maximum},{"chroma_error_rmse",pixels?std::sqrt(double(chromaSquare/(2*pixels))):0},
            {"same_pixel_error_delta_rmse",temporalPixels?Json(std::sqrt(double(temporalSquare/(3*temporalPixels)))):Json(nullptr)},
            {"metric_scope","paired_RR_observations_not_ground_truth; temporal_metric_is_unwarped_error_delta_not_ghosting_score"}};
    }
};
int main(int argc,char** argv)try
{
    Require(argc==2,"usage: native-replay native-replay-job.json");
    Require(std::filesystem::file_size(Path(argv[1]))<=32ull*1024*1024,"bounded replay job required");
    std::ifstream source{Path(argv[1])};Json job;source>>job;Require(bool(source),"job parse");
    Require(job.at("schema")=="fsrd-nrd-bridge-native-replay-job-v1","unsupported replay job");
    const auto& frames=job.at("frames");Require(frames.is_array()&&!frames.empty()&&frames.size()<=512,"bounded frame sequence required");
    const uint32_t width=job.at("render_extent").at(0),height=job.at("render_extent").at(1);
    Require(width>0&&height>0&&width<=8192&&height<=8192&&uint64_t(width)*height*72<=256ull*1024*1024,"bounded full-render extent required");
    Device device;Provider provider(job); // Context/module retire before the device, including on exceptions.
    const auto& first=frames.at(0);const auto& p=first.at("provider");
    Require(p.at("api_version").get<uint32_t>()==FFX_DENOISER_VERSION,"captured ABI version differs");
    Require(p.at("signal_flags").get<uint32_t>()==34,"only exact direct-diffuse/indirect-specular packet supported");
    uint64_t count=0;ffxQueryDescGetVersions versions{};versions.header.type=FFX_API_QUERY_DESC_TYPE_GET_VERSIONS;
    versions.createDescType=FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER;versions.device=device.device.Get();versions.outputCount=&count;
    Ff(provider.api.Query(nullptr,&versions.header),"version count");Require(count>0&&count<=64,"bounded provider versions required");
    std::vector<uint64_t> ids(size_t(count),0);std::vector<const char*> names(size_t(count),nullptr);
    versions.versionIds=ids.data();versions.versionNames=names.data();Ff(provider.api.Query(nullptr,&versions.header),"versions");
    Require(count<=ids.size(),"provider version count exceeded caller capacity");
    const uint64_t versionId=p.at("version_id");bool found=false;
    for(size_t i=0;i<ids.size();++i)if(ids[i]==versionId){found=true;Require(names[i]!=nullptr,"selected provider name missing");
        Require(std::string(names[i]).substr(0,127)==p.at("name").get<std::string>(),"selected provider name differs");}
    Require(found,"captured provider version id not exported by explicit DLL");
    ffxConfigureDescGlobalDebug logging{{FFX_API_CONFIGURE_DESC_TYPE_GLOBALDEBUG,nullptr},FFX_API_EFFECT_ID_DENOISER,SdkMessage,FFX_API_CONFIGURE_GLOBALDEBUG_LEVEL_VERBOSE};
    Ff(provider.api.Configure(nullptr,&logging.header),"global diagnostics");
    auto& selected=provider.selected;selected.header={FFX_API_DESC_TYPE_OVERRIDE_VERSION,nullptr};selected.versionId=versionId;
    auto& backend=provider.backend;backend.header={FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12,&selected.header};backend.device=device.device.Get();
    auto& create=provider.create;create.header={FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER,&backend.header};
    create.version=FFX_DENOISER_VERSION;create.maxRenderSize={width,height};create.signalFlags=34;
    create.checkerboardSignalFlags=p.at("checkerboard_signal_flags");create.flags=p.at("context_flags");
    Require((create.checkerboardSignalFlags&~34u)==0&&(create.flags&~3u)==0,"unsupported actual create flags");
    Ff(provider.api.CreateContext(&provider.context,&create.header,nullptr),"create captured RR context");
    Require(provider.context!=nullptr,"provider returned null context");
    std::array<float,8> defaults{},effective{};
    for(uint64_t key=1;key<=7;++key){ffxQueryDescDenoiserGetDefaultKeyValue query{{FFX_API_QUERY_DESC_TYPE_DENOISER_GET_DEFAULT_KEYVALUE,nullptr},key,1,defaults.data()+key-1};
        Ff(provider.api.Query(&provider.context,&query.header),"default query");}
    for(size_t i=0;i<8;++i){uint32_t bits=0;memcpy(&bits,&defaults[i],4);Require(bits==first.at("settings").at("provider_defaults").at(i).get<uint32_t>(),"actual provider default differs from captured default");
        bits=first.at("settings").at("provider_effective").at(i);memcpy(&effective[i],&bits,4);Require(std::isfinite(effective[i]),"nonfinite effective setting");}
    for(uint64_t key=1;key<=7;++key){ffxConfigureDescDenoiserKeyValue value{{FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE,nullptr},key,1,effective.data()+key-1};
        Ff(provider.api.Configure(&provider.context,&value.header),"configure exact effective settings");}
    constexpr std::array<DXGI_FORMAT,9> formats{DXGI_FORMAT_R32_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R10G10B10A2_UNORM,
        DXGI_FORMAT_R8G8B8A8_UNORM,DXGI_FORMAT_R8G8B8A8_UNORM,DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,
        DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT};
    std::array<uint32_t,7> inputFlags{};
    for(size_t i=0;i<7;++i){inputFlags[i]=first.at("inputs").at(i).at("source_native_resource_desc").at("flags");
        Require(inputFlags[i]==0||inputFlags[i]==D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,"unsupported actual input GPU flags");}
    std::array<Texture,9> textures;
    for(size_t i=0;i<textures.size();++i)textures[i]=device.Create(width,height,formats[i],i>=7,
        i<7?D3D12_RESOURCE_FLAGS(inputFlags[i]):D3D12_RESOURCE_FLAG_NONE);
    const bool debugging=(create.flags&FFX_DENOISER_ENABLE_DEBUGGING)!=0;Texture debugTexture;
    ComPtr<ID3D12DescriptorHeap> debugHeap,debugCpuHeap;
    if(debugging){debugTexture=device.Create(width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,true);
        D3D12_DESCRIPTOR_HEAP_DESC desc{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,1,D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE,0};
        Hr(device.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&debugHeap)),"debug UAV heap");
        desc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_NONE;Hr(device.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&debugCpuHeap)),"debug CPU UAV heap");
        D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};
        uav.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
        device.device->CreateUnorderedAccessView(debugTexture.resource.Get(),nullptr,&uav,debugHeap->GetCPUDescriptorHandleForHeapStart());
        device.device->CreateUnorderedAccessView(debugTexture.resource.Get(),nullptr,&uav,debugCpuHeap->GetCPUDescriptorHandleForHeapStart());}
    std::ofstream metrics(Path(job.at("metrics_file").get<std::string>()),std::ios::binary);Require(bool(metrics),"metrics output");
    std::array<std::vector<float>,2> previous;uint64_t totalNonfinite=0;
    for(size_t index=0;index<frames.size();++index)
    {
        const auto& frame=frames.at(index);Require(frame.at("ordinal").get<size_t>()==index,"frame order changed");
        const float radianceScale=frame.value("provider_radiance_scale",1.0f);
        const auto scales=frame.value("provider_radiance_scales",Json{{"diffuse",radianceScale},{"specular",radianceScale}});
        const std::array<float,2> radianceScales {scales.at("diffuse").get<float>(),scales.at("specular").get<float>()};
        for (const float value:radianceScales) Require(value>=1.f&&value<=4096.f&&std::has_single_bit(uint32_t(value))&&value==float(uint32_t(value)),"unsupported captured radiance scale");
        Hr(device.allocator->Reset(),"allocator reset");Hr(device.list->Reset(device.allocator.Get(),nullptr),"list reset");
        Require(frame.at("inputs").size()==7,"exactly seven actual inputs required");
        for(size_t i=0;i<7;++i){Require(frame.at("inputs").at(i).at("source_native_resource_desc").at("flags").get<uint32_t>()==inputFlags[i],"actual input GPU flags changed");
            device.Upload(textures[i],frame.at("inputs").at(i),width,height,i>=5?radianceScales[i-5]:1.f);}
        FrozenFile controlsFile(Path(frame.at("controls").at("file").get<std::string>()));auto controls=controlsFile.Payload(frame.at("controls"),184);
        ffxDispatchDescDenoiser dispatch{};dispatch.header.type=FFX_API_DISPATCH_DESC_TYPE_DENOISER;dispatch.commandList=device.list.Get();
        memcpy(reinterpret_cast<uint8_t*>(&dispatch)+264,controls.data(),184);
        Require(dispatch.renderSize.width==width&&dispatch.renderSize.height==height&&dispatch.frameIndex==frame.at("sdk_frame_index").get<uint32_t>()
            &&dispatch.flags==frame.at("actual_dispatch_flags").get<uint32_t>()&&(index||dispatch.flags&FFX_DENOISER_DISPATCH_RESET),"actual controls/frame/RESET mismatch");
        dispatch.linearDepth=textures[0].api;dispatch.motionVectors=textures[1].api;dispatch.normals=textures[2].api;
        dispatch.specularAlbedo=textures[3].api;dispatch.diffuseAlbedo=textures[4].api;
        ffxDispatchDescDenoiserDirectDiffuse diffuse{};diffuse.header.type=FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE;
        diffuse.signal={textures[5].api,textures[7].api,frame.at("provider").at("diffuse_checkerboard_origin").get<uint32_t>()};
        ffxDispatchDescDenoiserIndirectSpecular specular{};specular.header.type=FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR;
        specular.signal={textures[6].api,textures[8].api,frame.at("provider").at("specular_checkerboard_origin").get<uint32_t>()};
        dispatch.header.pNext=&diffuse.header;diffuse.header.pNext=&specular.header;
        ffxDispatchDescDenoiserDebugView debug{};
        if(debugging){Require(frame.at("settings").at("native_debug_view").get<int>()>=0,"debugging packet missing");
            ID3D12DescriptorHeap* heaps[]={debugHeap.Get()};device.list->SetDescriptorHeaps(1,heaps);const float zero[4]{};
            device.list->ClearUnorderedAccessViewFloat(debugHeap->GetGPUDescriptorHandleForHeapStart(),debugCpuHeap->GetCPUDescriptorHandleForHeapStart(),debugTexture.resource.Get(),zero,0,nullptr);
            D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;barrier.UAV.pResource=debugTexture.resource.Get();device.list->ResourceBarrier(1,&barrier);
            debug.header.type=FFX_API_DISPATCH_DESC_TYPE_DENOISER_DEBUG_VIEW;debug.output=debugTexture.api;debug.outputSize={width,height};
            debug.mode=frame.at("settings").at("native_debug_view");debug.viewportIndex=frame.at("settings").at("native_debug_viewport");specular.header.pNext=&debug.header;}
        Require(memcmp(reinterpret_cast<const uint8_t*>(&dispatch)+264,controls.data(),184)==0,"reconstructed actual184 controls changed");
        Ff(provider.api.Dispatch(&provider.context,&dispatch.header),"replay captured provider dispatch");
        device.Readback(textures[7]);device.Readback(textures[8]);device.Submit();
        ErrorMetrics diffuseMetrics,specularMetrics;
        auto d=diffuseMetrics.Read(textures[7],frame.at("reference_diffuse"),width,height,previous[0],radianceScales[0]);
        auto s=specularMetrics.Read(textures[8],frame.at("reference_specular"),width,height,previous[1],radianceScales[1]);
        totalNonfinite+=diffuseMetrics.nonfinite+specularMetrics.nonfinite;
        metrics<<Json{{"ordinal",index},{"sdk_frame_index",dispatch.frameIndex},{"diffuse",d},{"specular",s}}.dump()<<'\n';
        Require(bool(metrics),"metrics write");
    }
    metrics.close();Require(bool(metrics),"metrics flush");Ff(provider.api.DestroyContext(&provider.context,nullptr),"destroy replay context");
    provider.context=nullptr; // Own handle is retired exactly once; no undocumented SDK nulling postcondition.
    Json result{{"status",totalNonfinite?"FAIL":"PASS"},{"frames",frames.size()},{"actual_sdk_dispatches",frames.size()},
        {"provider_sha256",job.at("provider_sha256")},{"adapter",device.adapter},{"debug_errors",device.errors},{"debug_warnings",device.warnings},
        {"sdk_errors",sdkErrors.load()},{"sdk_warnings",sdkWarnings.load()},{"nonfinite_output_pixels",totalNonfinite},
        {"metrics_file",job.at("metrics_file")},{"loaded_disk_identity_verified",true},{"loaded_memory_image_equality_attested",false},
        {"comparison_status","metrics_only_no_automatic_quality_verdict"},
        {"scope","actual_RR_inputs/raw_RR_observations; no_native_NRD_output; no_bitexact_or_game_quality_claim"}};
    std::ofstream summary(Path(job.at("summary_file").get<std::string>()),std::ios::binary);summary<<result.dump(2)<<'\n';summary.close();Require(bool(summary),"summary write");
    Require(totalNonfinite==0,"nonfinite replay/captured outputs");std::cout<<result.dump()<<'\n';return 0;
}
catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
