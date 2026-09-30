// CPU-only serialized root-signature inspection; creates no device or queue.
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <wrl/client.h>
#include <fstream>
#include <iostream>
#include <vector>
#include <string>
#include <stdexcept>
using Microsoft::WRL::ComPtr;
int main(int argc,char** argv) try
{
    if(argc!=2)throw std::runtime_error("usage root_inspector rootblob.bin");
    std::ifstream in(argv[1],std::ios::binary);in.seekg(0,std::ios::end);size_t n=static_cast<size_t>(in.tellg());in.seekg(0);
    std::vector<char> bytes(n);in.read(bytes.data(),n);if(!in)throw std::runtime_error("read");
    ComPtr<ID3D12VersionedRootSignatureDeserializer> deserializer;
    auto hr=D3D12CreateVersionedRootSignatureDeserializer(bytes.data(),bytes.size(),IID_PPV_ARGS(&deserializer));
    if(FAILED(hr))throw std::runtime_error("root deserialize HRESULT="+std::to_string(UINT(hr)));
    auto d=deserializer->GetUnconvertedRootSignatureDesc();
    std::cout<<"{\"version_enum\":"<<UINT(d->Version)<<",\"root_flags\":";
    if(d->Version==D3D_ROOT_SIGNATURE_VERSION_1_0) {
        const auto& s=d->Desc_1_0;std::cout<<UINT(s.Flags)<<",\"parameters\":[";
        for(UINT i=0;i<s.NumParameters;++i){auto& p=s.pParameters[i];if(i)std::cout<<',';
            std::cout<<"{\"index\":"<<i<<",\"type\":"<<UINT(p.ParameterType)<<",\"visibility\":"<<UINT(p.ShaderVisibility);
            if(p.ParameterType==D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE) {
                std::cout<<",\"ranges\":[";for(UINT j=0;j<p.DescriptorTable.NumDescriptorRanges;++j){auto& r=p.DescriptorTable.pDescriptorRanges[j];if(j)std::cout<<',';
                    std::cout<<"{\"type\":"<<UINT(r.RangeType)<<",\"count\":"<<r.NumDescriptors<<",\"base_register\":"<<r.BaseShaderRegister<<",\"space\":"<<r.RegisterSpace<<",\"offset\":"<<r.OffsetInDescriptorsFromTableStart<<",\"flags\":null}";}std::cout<<']';
            }else if(p.ParameterType!=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS)std::cout<<",\"register\":"<<p.Descriptor.ShaderRegister<<",\"space\":"<<p.Descriptor.RegisterSpace<<",\"flags\":null";
            std::cout<<'}';}
        std::cout<<"],\"static_samplers\":"<<s.NumStaticSamplers;
    } else if(d->Version==D3D_ROOT_SIGNATURE_VERSION_1_1) {
        const auto& s=d->Desc_1_1;std::cout<<UINT(s.Flags)<<",\"parameters\":[";
        for(UINT i=0;i<s.NumParameters;++i){auto& p=s.pParameters[i];if(i)std::cout<<',';
            std::cout<<"{\"index\":"<<i<<",\"type\":"<<UINT(p.ParameterType)<<",\"visibility\":"<<UINT(p.ShaderVisibility);
            if(p.ParameterType==D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE) {
                std::cout<<",\"ranges\":[";for(UINT j=0;j<p.DescriptorTable.NumDescriptorRanges;++j){auto& r=p.DescriptorTable.pDescriptorRanges[j];if(j)std::cout<<',';
                    std::cout<<"{\"type\":"<<UINT(r.RangeType)<<",\"count\":"<<r.NumDescriptors<<",\"base_register\":"<<r.BaseShaderRegister<<",\"space\":"<<r.RegisterSpace<<",\"offset\":"<<r.OffsetInDescriptorsFromTableStart<<",\"flags\":"<<UINT(r.Flags)<<'}';}std::cout<<']';
            }else if(p.ParameterType!=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS)std::cout<<",\"register\":"<<p.Descriptor.ShaderRegister<<",\"space\":"<<p.Descriptor.RegisterSpace<<",\"flags\":"<<UINT(p.Descriptor.Flags);
            std::cout<<'}';}
        std::cout<<"],\"static_samplers\":"<<s.NumStaticSamplers;
    } else throw std::runtime_error("unsupported root signature version");
    std::cout<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
