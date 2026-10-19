#pragma once
#include "precompile/FSRDNrdLightingGuard_Shader.h"
#include "precompile/FSRDNrdLightingGuardApply_Shader.h"
#include <bit>
#include <cmath>
#include <d3d12.h>
#include <wrl/client.h>
#include <array>
#include <algorithm>
#include <memory>
#include <string>
#include <vector>

// Serialized by RRWrapper. Work owns its exact history generation and descriptor slot until the RR lease retires.
class FSRDNrdLightingGuardDx12
{
    friend struct FSRDLightingGuardTestAccess;
    using Resource=Microsoft::WRL::ComPtr<ID3D12Resource>;
    struct Slot { Resource motion; Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> heap; uint64_t bytes=0; };
    struct State
    {
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        Microsoft::WRL::ComPtr<ID3D12RootSignature> root,applyRoot;
        Microsoft::WRL::ComPtr<ID3D12PipelineState> pso,applyPso;
        std::array<Resource,2> meanVar,fast,tile;
        Resource change,support;
        std::vector<std::shared_ptr<Slot>> slots;
        uint32_t width=0,height=0,lastFrame=0,age=0;
        uint64_t bytes=0;
        bool valid=false;
    };
    std::shared_ptr<State> state_;
    static bool Texture(ID3D12Device* device,uint32_t w,uint32_t h,DXGI_FORMAT format,Resource& resource,uint64_t& bytes)
    {
        D3D12_HEAP_PROPERTIES heap {};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC desc {};desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;desc.Width=w;desc.Height=h;
        desc.DepthOrArraySize=1;desc.MipLevels=1;desc.Format=format;desc.SampleDesc.Count=1;
        desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        if(FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,nullptr,IID_PPV_ARGS(&resource))))return false;
        bytes+=device->GetResourceAllocationInfo(0,1,&desc).SizeInBytes;
        return true;
    }
  public:
    struct Work
    {
      private:
        friend class FSRDNrdLightingGuardDx12;
        friend struct FSRDLightingGuardTestAccess;
        std::shared_ptr<State> state;
        std::shared_ptr<Slot> slot;
        std::array<Resource,4> inputs;
      public:
        ID3D12Resource* Motion()const noexcept{return slot?slot->motion.Get():nullptr;}
    };
    using Lease=std::shared_ptr<Work>;
    void Reset()noexcept{state_.reset();}
    void Invalidate()noexcept{if(state_)state_->valid=false;}
    uint64_t ImageBytes()const noexcept
    {
        uint64_t bytes=state_?state_->bytes:0;
        if(state_)for(const auto& slot:state_->slots)bytes+=slot->bytes;
        return bytes;
    }
    bool Before(ID3D12Device* device,ID3D12GraphicsCommandList* list,uint32_t width,uint32_t height,uint32_t frame,
                ID3D12Resource* diffuse,ID3D12Resource* specular,ID3D12Resource* motion,ID3D12Resource* depth,
                Lease& out,std::string& error,float disocclusion,float projectionToViewY,float maxPreviousDepth,
                ID3D12QueryHeap* timestamps=nullptr,uint32_t timestampOffset=0)noexcept
    {
        out.reset();error.clear();
        try
        {
            if(!device||!list||!width||!height||!diffuse||!specular||!motion||!depth||
                !std::isfinite(disocclusion)||disocclusion<0||!std::isfinite(projectionToViewY)||projectionToViewY<=0||
                !std::isfinite(maxPreviousDepth)||maxPreviousDepth<=0||maxPreviousDepth>65504)
            {error="Invalid RR lighting-validation inputs";return false;}
            if(!state_||state_->device.Get()!=device||state_->width!=width||state_->height!=height)
            {
                auto s=std::make_shared<State>();s->device=device;s->width=width;s->height=height;
                if(FAILED(device->CreateRootSignature(0,FSRDNrdLightingGuard_cso,sizeof(FSRDNrdLightingGuard_cso),IID_PPV_ARGS(&s->root))))
                {error="RR lighting-validation root creation failed";return false;}
                D3D12_COMPUTE_PIPELINE_STATE_DESC pso {};pso.pRootSignature=s->root.Get();
                pso.CS={FSRDNrdLightingGuard_cso,sizeof(FSRDNrdLightingGuard_cso)};
                if(FAILED(device->CreateComputePipelineState(&pso,IID_PPV_ARGS(&s->pso))))
                {error="RR lighting-validation pipeline creation failed";return false;}
                if(FAILED(device->CreateRootSignature(0,FSRDNrdLightingGuardApply_cso,sizeof(FSRDNrdLightingGuardApply_cso),IID_PPV_ARGS(&s->applyRoot))))
                {error="RR lighting-validation apply root creation failed";return false;}
                pso.pRootSignature=s->applyRoot.Get();
                pso.CS={FSRDNrdLightingGuardApply_cso,sizeof(FSRDNrdLightingGuardApply_cso)};
                if(FAILED(device->CreateComputePipelineState(&pso,IID_PPV_ARGS(&s->applyPso))))
                {error="RR lighting-validation apply pipeline creation failed";return false;}
                uint32_t tw=(width+31)/32,th=(height+31)/32;
                for(unsigned i=0;i<2;i++)
                    if(!Texture(device,tw*4,th*4,DXGI_FORMAT_R32G32B32A32_FLOAT,s->meanVar[i],s->bytes)||
                       !Texture(device,tw*4,th*4,DXGI_FORMAT_R32G32_FLOAT,s->fast[i],s->bytes)||
                       !Texture(device,tw,th,DXGI_FORMAT_R32_UINT,s->tile[i],s->bytes))
                    {error="RR lighting-validation history allocation failed";return false;}
                if(!Texture(device,tw*4,th*4,DXGI_FORMAT_R32G32_FLOAT,s->change,s->bytes))
                {error="RR lighting-validation change-map allocation failed";return false;}
                if(!Texture(device,tw*4,th*4,DXGI_FORMAT_R32G32B32A32_FLOAT,s->support,s->bytes))
                {error="RR lighting-validation local-support allocation failed";return false;}
                state_=std::move(s);
            }
            auto work=std::make_shared<Work>();work->state=state_;work->inputs={diffuse,specular,motion,depth};
            for(const auto& slot:state_->slots)if(slot.use_count()==1){work->slot=slot;break;}
            if(!work->slot)
            {
                if(state_->slots.size()>=32){error="RR lighting-validation recording slots are full";return false;}
                auto slot=std::make_shared<Slot>();
                if(!Texture(device,width,height,DXGI_FORMAT_R16G16B16A16_FLOAT,slot->motion,slot->bytes))
                {error="RR lighting-validation motion allocation failed";return false;}
                D3D12_DESCRIPTOR_HEAP_DESC heap {};heap.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
                heap.NumDescriptors=16;heap.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
                if(FAILED(device->CreateDescriptorHeap(&heap,IID_PPV_ARGS(&slot->heap))))
                {error="RR lighting-validation descriptors failed";return false;}
                state_->slots.push_back(slot);work->slot=std::move(slot);
            }
            const auto& s=*state_;const uint32_t next=frame&1,previous=next^1;
            std::array<ID3D12Resource*,10> srvs {diffuse,specular,motion,depth,s.meanVar[previous].Get(),s.fast[previous].Get(),s.tile[previous].Get(),s.tile[next].Get(),s.change.Get(),s.support.Get()};
            std::array<ID3D12Resource*,6> uavs {work->slot->motion.Get(),s.meanVar[next].Get(),s.fast[next].Get(),s.tile[next].Get(),s.change.Get(),s.support.Get()};
            auto cpu=work->slot->heap->GetCPUDescriptorHandleForHeapStart();
            const auto stride=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
            const auto srv=[&](ID3D12Resource* resource)
            {
                D3D12_SHADER_RESOURCE_VIEW_DESC view {};view.Format=resource->GetDesc().Format;
                view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
                view.Texture2D.MipLevels=1;device->CreateShaderResourceView(resource,&view,cpu);cpu.ptr+=stride;
            };
            const auto uav=[&](ID3D12Resource* resource)
            {
                D3D12_UNORDERED_ACCESS_VIEW_DESC view {};view.Format=resource->GetDesc().Format;
                view.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;device->CreateUnorderedAccessView(resource,nullptr,&view,cpu);cpu.ptr+=stride;
            };
            // Per-pass ranges bind only resources valid in that pass. Static descriptor validation
            // applies to whole ranges even when a compiled entry point does not read one descriptor.
            for(unsigned i=0;i<7;i++)srv(srvs[i]);
            for(unsigned i=1;i<6;i++)uav(uavs[i]);
            srv(srvs[7]);srv(srvs[8]);srv(srvs[9]);uav(uavs[0]);
            // Everything that can fail is prepared before touching the command list.
            std::array<D3D12_RESOURCE_BARRIER,6> barriers {};
            for(unsigned i=0;i<6;i++)
            {
                barriers[i].Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
                barriers[i].Transition={uavs[i],D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
            }
            list->ResourceBarrier(6,barriers.data());list->SetPipelineState(s.pso.Get());list->SetComputeRootSignature(s.root.Get());
            ID3D12DescriptorHeap* heaps[]={work->slot->heap.Get()};list->SetDescriptorHeaps(1,heaps);
            const bool reset=!s.valid||uint32_t(frame-s.lastFrame)!=1;
            const uint32_t age=reset?1:std::min(s.age+1,1000000u);
            std::array<uint32_t,8> constants {width,height,frame,uint32_t(reset),age,std::bit_cast<uint32_t>(disocclusion),
                std::bit_cast<uint32_t>(projectionToViewY),std::bit_cast<uint32_t>(maxPreviousDepth)};
            list->SetComputeRoot32BitConstants(0,8,constants.data(),0);
            auto gpu=work->slot->heap->GetGPUDescriptorHandleForHeapStart();list->SetComputeRootDescriptorTable(1,gpu);
            gpu.ptr+=7*stride;list->SetComputeRootDescriptorTable(2,gpu);
            if(timestamps)list->EndQuery(timestamps,D3D12_QUERY_TYPE_TIMESTAMP,timestampOffset);
            list->Dispatch((width+31)/32,(height+31)/32,1);
            if(timestamps)list->EndQuery(timestamps,D3D12_QUERY_TYPE_TIMESTAMP,timestampOffset+1);
            for(auto& barrier:barriers)std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter);
            // Publish all statistics, especially the tile-active bit, before the separate apply pass.
            // Motion stays UAV until that pass completes; each root binds only its own live ranges.
            list->ResourceBarrier(5,barriers.data()+1);list->SetPipelineState(s.applyPso.Get());
            list->SetComputeRootSignature(s.applyRoot.Get());list->SetComputeRoot32BitConstants(0,8,constants.data(),0);
            gpu=work->slot->heap->GetGPUDescriptorHandleForHeapStart();gpu.ptr+=2*stride;list->SetComputeRootDescriptorTable(1,gpu);
            gpu.ptr+=10*stride;list->SetComputeRootDescriptorTable(2,gpu);
            gpu.ptr+=3*stride;list->SetComputeRootDescriptorTable(3,gpu);
            if(timestamps)list->EndQuery(timestamps,D3D12_QUERY_TYPE_TIMESTAMP,timestampOffset+2);
            list->Dispatch((width+7)/8,(height+7)/8,1);
            if(timestamps)list->EndQuery(timestamps,D3D12_QUERY_TYPE_TIMESTAMP,timestampOffset+3);
            list->ResourceBarrier(1,barriers.data());state_->valid=true;state_->lastFrame=frame;state_->age=age;
            out=std::move(work);return true;
        }
        catch(...){Invalidate();error="RR lighting-validation preparation failed";return false;}
    }
};
