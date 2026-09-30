// Isolated public default-scalar query probe. No RR/Configure/caller submission.
#define NOMINMAX
#define _WINDOWS
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <sstream>
#include <string>
#include <array>
#include <vector>
#include <cstring>
#include <cmath>
#include <stdexcept>
#include "ffx_api_loader.h"
#include "dx12/ffx_api_dx12.h"
#include "ffx_denoiser.h"
using Microsoft::WRL::ComPtr;
constexpr uint32_t Sentinel=0x7fc12345u;
constexpr uint64_t Keys[]={FFX_API_CONFIGURE_DENOISER_KEY_DISOCCLUSION_THRESHOLD,
 FFX_API_CONFIGURE_DENOISER_KEY_CROSS_BILATERAL_NORMAL_STRENGTH,
 FFX_API_CONFIGURE_DENOISER_KEY_STABILITY_BIAS,FFX_API_CONFIGURE_DENOISER_KEY_MAX_RADIANCE,
 FFX_API_CONFIGURE_DENOISER_KEY_RADIANCE_CLIP_STD_K,FFX_API_CONFIGURE_DENOISER_KEY_GAUSSIAN_KERNEL_RELAXATION};
struct State {
 unsigned seq=0,ce=0,cr=0,created=0,qe=0,qr=0,qo=0,de=0,dr=0,destroyed=0;
 unsigned errors=0,warnings=0; bool ambiguous=false,accepted=false;
 void event(const char* stage,uint64_t key=0,uint32_t rc=0,bool nonnull=false,uint32_t bits=0) {
  std::cout<<"QUERY_EVENT {\"v\":1,\"seq\":"<<seq++<<",\"stage\":\""<<stage
   <<"\",\"key\":"<<key<<",\"rc\":"<<rc<<",\"nonnull\":"<<(nonnull?"true":"false")
   <<",\"bits\":"<<bits<<",\"create_entry\":"<<ce<<",\"create_returned\":"<<cr
   <<",\"created\":"<<created<<",\"query_entry\":"<<qe<<",\"query_returned\":"<<qr
   <<",\"query_ok\":"<<qo<<",\"destroy_entry\":"<<de<<",\"destroy_returned\":"<<dr
   <<",\"destroyed\":"<<destroyed<<",\"rr_dispatch\":0,\"configure\":0,\"owned_execute\":0"
   <<",\"d3d_errors\":"<<errors<<",\"d3d_warnings\":"<<warnings
   <<",\"ownership_uncertain\":"<<(ambiguous?"true":"false")
   <<",\"accepted\":"<<(accepted?"true":"false")<<"}\n"<<std::flush;
  if(!std::cout)throw std::runtime_error("stdout event write failed");
 }
};
void hr(HRESULT value,const char* what){if(FAILED(value))throw std::runtime_error(what);}
int main(int argc,char** argv) {
 State s; HMODULE module=nullptr; ffxFunctions api{}; ffxContext context=nullptr;
 ComPtr<ID3D12Device> dev; ComPtr<IDXGIFactory6> factory; ComPtr<IDXGIAdapter1> adapter;
 ComPtr<ID3D12InfoQueue> info;
 // These pointed-to creation descriptors live through explicit DestroyContext.
 ffxCreateBackendDX12Desc backend{{FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12,nullptr},nullptr};
 ffxCreateContextDescDenoiser create{{FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER,&backend.header},
  FFX_DENOISER_VERSION,{128,80},FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE|FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR,
  0,FFX_DENOISER_ENABLE_VALIDATION};
 std::array<float,6> values{};std::array<uint32_t,6> raw{};
 for(auto& v:values)std::memcpy(&v,&Sentinel,4);
 bool live=false,primaryFailure=false,terminalWritten=false;
 auto destroyOnce=[&]() {
  if(!live||s.de)return;
  ++s.de;
  try{s.event("destroy_start");}catch(const std::exception& x){primaryFailure=true;std::cerr<<x.what()<<'\n';}
  const auto rc=api.DestroyContext(&context,nullptr);++s.dr;
  if(rc==FFX_API_RETURN_OK){s.destroyed=1;live=false;}else{s.ambiguous=true;primaryFailure=true;}
  s.event("destroy_return",0,rc,context!=nullptr);
 };
 try {
  s.event("boot");
  if(argc!=2)throw std::runtime_error("usage: fsrd_default_query job.txt");
  const auto folder=std::filesystem::absolute(argv[1]).parent_path();
  std::ifstream job(argv[1]);std::string dll;job>>std::quoted(dll);job>>std::ws;
  if(!job||dll.empty()||!job.eof())throw std::runtime_error("invalid exact single-provider job");
  ComPtr<ID3D12Debug> debug;hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)),"debug layer unavailable");debug->EnableDebugLayer();
  hr(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)),"factory");
  hr(factory->EnumAdapterByGpuPreference(0,DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,IID_PPV_ARGS(&adapter)),"adapter");
  DXGI_ADAPTER_DESC1 ad{};hr(adapter->GetDesc1(&ad),"adapter desc");
  LARGE_INTEGER driver{};hr(adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice),&driver),"driver identity");
  hr(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&dev)),"device");
  hr(dev.As(&info),"D3D ordinary diagnostics unavailable");backend.device=dev.Get();
  const auto requested=std::filesystem::canonical(dll);
  module=LoadLibraryExW(requested.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
  if(!module)throw std::runtime_error("provider LoadLibrary failed");
  ffxLoadFunctions(&api,module);if(!api.CreateContext||!api.Query||!api.DestroyContext)throw std::runtime_error("required query exports missing");
  wchar_t actual[32768]{};const DWORD n=GetModuleFileNameW(module,actual,32768);
  if(!n||n>=32768||_wcsicmp(requested.c_str(),std::filesystem::canonical(actual).c_str()))throw std::runtime_error("loaded provider path mismatch");
  std::cout<<"QUERY_META {\"v\":1,\"api\":"<<FFX_DENOISER_VERSION<<",\"width\":128,\"height\":80,\"signals\":34,\"checkerboard\":0,\"create_flags\":2,\"debug_layer\":1,\"provider_path_verified\":true,\"vendor_id\":"<<ad.VendorId<<",\"device_id\":"<<ad.DeviceId<<",\"luid_low\":"<<ad.AdapterLuid.LowPart<<",\"luid_high\":"<<ad.AdapterLuid.HighPart<<",\"driver\":"<<driver.QuadPart<<",\"SDK_callback_warning_count_available\":false}\n"<<std::flush;
  if(!std::cout)throw std::runtime_error("stdout metadata write failed");
  ++s.ce;s.event("create_start");
  const auto rc=api.CreateContext(&context,&create.header,nullptr);++s.cr;
  if(rc==FFX_API_RETURN_OK&&context){s.created=1;live=true;}
  else{primaryFailure=true;s.ambiguous=context!=nullptr;}
  s.event("create_return",0,rc,context!=nullptr);
  if(live)for(unsigned i=0;i<6;++i){
   ++s.qe;s.event("query_start",Keys[i]);
   ffxQueryDescDenoiserGetDefaultKeyValue query{{FFX_API_QUERY_DESC_TYPE_DENOISER_GET_DEFAULT_KEYVALUE,nullptr},Keys[i],1,&values[i]};
   const auto queryRc=api.Query(&context,&query.header);++s.qr;if(queryRc==FFX_API_RETURN_OK)++s.qo;
   std::memcpy(&raw[i],&values[i],4);
   s.event("query_return",Keys[i],queryRc,context!=nullptr,raw[i]);
   if(queryRc!=FFX_API_RETURN_OK){primaryFailure=true;break;}
  }
  destroyOnce();
  // Retain every returned slot's raw bits including failed/unwritten data; no repair.
  std::ofstream out(folder/"query_values.bin",std::ios::binary);
  out.write(reinterpret_cast<const char*>(raw.data()),s.qr*4);out.close();
  if(!out)throw std::runtime_error("raw query output write failed");
  if(info)for(UINT64 i=0;i<info->GetNumStoredMessages();++i){
   SIZE_T size=0;hr(info->GetMessage(i,nullptr,&size),"diagnostic size");std::vector<char>b(size);auto* m=reinterpret_cast<D3D12_MESSAGE*>(b.data());hr(info->GetMessage(i,m,&size),"diagnostic message");
   if(m->Severity<=D3D12_MESSAGE_SEVERITY_ERROR){++s.errors;std::cerr<<m->pDescription<<'\n';}
   else if(m->Severity==D3D12_MESSAGE_SEVERITY_WARNING){++s.warnings;std::cerr<<m->pDescription<<'\n';}
  }
  hr(dev->GetDeviceRemovedReason(),"device removed");
  bool numeric=true;for(unsigned i=0;i<s.qr;++i)numeric=numeric&&std::isfinite(values[i])&&raw[i]!=Sentinel;
  s.accepted=!primaryFailure&&s.created==1&&s.qr==6&&s.qo==6&&s.destroyed==1&&!s.errors&&!s.warnings&&numeric;
  s.event(s.accepted?"complete":"failed");terminalWritten=true;
 } catch(const std::exception& e){
  primaryFailure=true;s.accepted=false;std::cerr<<e.what()<<'\n';
  try{destroyOnce();}catch(const std::exception& x){std::cerr<<x.what()<<'\n';}
  if(!terminalWritten)try{s.event("failed");terminalWritten=true;}catch(...){/* Missing footer means unknown totals. */}
 }
 if(s.ambiguous||(live&&!s.destroyed)){
  // Ownership after failed Create/Destroy is unspecified: keep module/descriptors/device
  // alive until owned-process termination; no speculative retry/unload or API-cleanup claim.
  ExitProcess(1);
 }
 if(module)FreeLibrary(module);
 return s.accepted?0:1;
}
