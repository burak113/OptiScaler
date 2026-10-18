#pragma once
#include "FSRDRadianceScale.h"
#include "precompile/FSRDRadianceScale_Shader.h"
#include <upscalers/fsr31/FSRDRRInterop.h>
#if !defined(FSRD_NRD_BRIDGE_RR_TEST_BACKEND) && !defined(FSRD_RADIANCE_SCALE_TEST)
#include <resource_tracking/ResTrack_dx12.h>
#endif
#include <wrl/client.h>
#include <array>
#include <bit>
#include <memory>
#include <string>
#include <vector>

// Callers serialize recording, as they do for their existing conversion/provider
// objects. Slots cannot be rewritten until their real command-list lease retires.
class FSRDRadianceScaleDx12
{
    using Resource = Microsoft::WRL::ComPtr<ID3D12Resource>;
    struct Slot { Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> descriptors; };
    struct State
    {
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        Microsoft::WRL::ComPtr<ID3D12RootSignature> root;
        Microsoft::WRL::ComPtr<ID3D12PipelineState> pipeline;
        std::vector<std::shared_ptr<Slot>> slots;
    };
    std::shared_ptr<State> state_;
  public:
    struct Work
    {
      private:
        friend class FSRDRadianceScaleDx12;
        std::shared_ptr<State> state;
        std::shared_ptr<Slot> slot;
        std::array<Resource,4> inputs, outputs;
        std::array<D3D12_RESOURCE_STATES,4> inputStates {};
        std::array<float,4> factors {};
        ID3D12GraphicsCommandList* list = nullptr;
        uint32_t width = 0, height = 0, count = 0;
        bool restored = false;
    };
    using Lease = std::shared_ptr<Work>;

    // Fully validates/allocates/retains before the first GPU mutation.
    bool Before(ID3D12Device* device, ID3D12GraphicsCommandList* list,
                const ffxDispatchDescDenoiser& dispatch, const FSRDRadianceScaleSettings& settings,
                Lease& out, std::string& error) noexcept
    {
        out.reset(); error.clear();
        if (!settings.enabled) return true;
        try
        {
            if (!device || !list || !dispatch.renderSize.width || !dispatch.renderSize.height ||
                !ValidFSRDRadianceScale(settings.diffuse) || !ValidFSRDRadianceScale(settings.specular))
            { error = "Invalid shared RR radiance scale request"; return false; }
            auto work = std::make_shared<Work>();
            work->list = list; work->width = dispatch.renderSize.width; work->height = dispatch.renderSize.height;
            uint32_t visited = 0;
            bool nonUnity = false;
            for (auto* header = dispatch.header.pNext; header; header = header->pNext)
            {
                if (++visited > 16) { error = "RR signal chain is cyclic or too long"; return false; }
                const bool diffuse = header->type == FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE ||
                                     header->type == FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE;
                const bool specular = header->type == FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR ||
                                      header->type == FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR;
                if (!diffuse && !specular) continue; // AO, visibility and debug are dimensionless.
                if (work->count == 4) { error = "Too many RR radiance signals"; return false; }
                static_assert(sizeof(ffxDispatchDescDenoiserDirectDiffuse) == sizeof(ffxDispatchDescDenoiserIndirectSpecular));
                const auto& signal = reinterpret_cast<const ffxDispatchDescDenoiserDirectDiffuse*>(header)->signal;
                const auto index = work->count++;
                work->inputs[index] = static_cast<ID3D12Resource*>(signal.input.resource);
                work->outputs[index] = static_cast<ID3D12Resource*>(signal.output.resource);
                work->factors[index] = float(diffuse ? settings.diffuse : settings.specular);
                nonUnity |= work->factors[index] != 1.0f;
                if (signal.input.state == FFX_API_RESOURCE_STATE_COMPUTE_READ)
                    work->inputStates[index] = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
                else if (signal.input.state == FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ)
                    work->inputStates[index] = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
                else { error = "RR radiance input is not in a supported shader-read state"; return false; }
                if (signal.output.state != FFX_API_RESOURCE_STATE_UNORDERED_ACCESS)
                { error = "RR radiance output is not UAV"; return false; }
                for (auto* resource : {work->inputs[index].Get(),work->outputs[index].Get()})
                {
                    if (!resource) { error = "Missing RR radiance resource"; return false; }
                    const auto desc = resource->GetDesc();
                    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.Width < work->width ||
                        desc.Height < work->height || desc.DepthOrArraySize != 1 || desc.MipLevels != 1 ||
                        desc.SampleDesc.Count != 1 || desc.Format != DXGI_FORMAT_R16G16B16A16_FLOAT ||
                        !(desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS))
                    { error = "Shared RR radiance scaling requires owned RGBA16F UAV textures"; return false; }
                    Microsoft::WRL::ComPtr<ID3D12Device> resourceDevice;
                    if (FAILED(resource->GetDevice(IID_PPV_ARGS(&resourceDevice))) || resourceDevice.Get() != device)
                    { error = "RR radiance resource belongs to another device"; return false; }
                }
            }
            if (!work->count || !nonUnity) return true;
            for (uint32_t i=0;i<work->count;++i)
                for (uint32_t j=0;j<work->count;++j)
                    if (work->inputs[i] == work->outputs[j] ||
                        (i != j && (work->inputs[i] == work->inputs[j] || work->outputs[i] == work->outputs[j])))
                    { error = "Aliased RR radiance resources cannot be scaled in place"; return false; }
            if (!state_ || state_->device.Get() != device)
            {
                auto state = std::make_shared<State>(); state->device = device;
                if (FAILED(device->CreateRootSignature(0,FSRDRadianceScale_cso,sizeof(FSRDRadianceScale_cso),IID_PPV_ARGS(&state->root))))
                { error = "Shared RR radiance root creation failed"; return false; }
                D3D12_COMPUTE_PIPELINE_STATE_DESC desc {};
                desc.pRootSignature = state->root.Get(); desc.CS = {FSRDRadianceScale_cso,sizeof(FSRDRadianceScale_cso)};
                if (FAILED(device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&state->pipeline))))
                { error = "Shared RR radiance pipeline creation failed"; return false; }
                state_ = std::move(state);
            }
            work->state = state_;
            for (const auto& slot : state_->slots) if (slot.use_count() == 1) { work->slot = slot; break; }
            if (!work->slot)
            {
                if (state_->slots.size() >= 32) { error = "Shared RR radiance recording slots are full"; return false; }
                auto slot = std::make_shared<Slot>();
                D3D12_DESCRIPTOR_HEAP_DESC desc {}; desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
                desc.NumDescriptors = 8; desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
                if (FAILED(device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&slot->descriptors))))
                { error = "Shared RR radiance descriptor creation failed"; return false; }
                state_->slots.push_back(slot); work->slot = std::move(slot);
            }
            auto cpu = work->slot->descriptors->GetCPUDescriptorHandleForHeapStart();
            const auto stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
            for (uint32_t i=0;i<8;++i)
            {
                D3D12_UNORDERED_ACCESS_VIEW_DESC view {}; view.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
                view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
                auto* resource = i < 4 ? work->inputs[i].Get() : work->outputs[i-4].Get();
                device->CreateUnorderedAccessView(resource,nullptr,&view,cpu); cpu.ptr += stride;
            }
            if (!ResTrack_Dx12::RetainComputeDispatch(device,list,work))
            { error = "Shared RR radiance recording lifetime is unavailable"; return false; }
            out = std::move(work);
            Record(*out,false);
            return true;
        }
        catch (...) { error = "Shared RR radiance preparation failed"; return false; }
    }
    static void Restore(const Lease& work) noexcept
    {
        if (!work || work->restored) return;
        Record(*work,true); work->restored = true;
    }
    struct Scope
    {
        Lease work;
        ~Scope() { Restore(work); }
    };
  private:
    static void Record(const Work& work, bool restore) noexcept
    {
        auto* list = work.list;
        std::array<D3D12_RESOURCE_BARRIER,8> barriers {};
        for (uint32_t i=0;i<work.count;++i)
        {
            barriers[i].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barriers[i].Transition = {work.inputs[i].Get(),D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                work.inputStates[i],D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
            barriers[i+work.count].Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
            barriers[i+work.count].UAV.pResource = work.outputs[i].Get();
        }
        list->ResourceBarrier(work.count*(restore?2:1),barriers.data());
        list->SetPipelineState(work.state->pipeline.Get()); list->SetComputeRootSignature(work.state->root.Get());
        ID3D12DescriptorHeap* heaps[] {work.slot->descriptors.Get()}; list->SetDescriptorHeaps(1,heaps);
        std::array<uint32_t,8> constants {work.width,work.height,work.count,restore?1u:0u};
        for (uint32_t i=0;i<work.count;++i)
            constants[i+4] = std::bit_cast<uint32_t>(restore?1.0f/work.factors[i]:work.factors[i]);
        list->SetComputeRoot32BitConstants(0,8,constants.data(),0);
        list->SetComputeRootDescriptorTable(1,work.slot->descriptors->GetGPUDescriptorHandleForHeapStart());
        list->Dispatch((work.width+7)/8,(work.height+7)/8,1);
        for (uint32_t i=0;i<work.count;++i)
            std::swap(barriers[i].Transition.StateBefore,barriers[i].Transition.StateAfter);
        list->ResourceBarrier(work.count*(restore?2:1),barriers.data());
    }
};
