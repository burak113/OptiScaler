// Post-motion level anchor (task 25 T3 ii), GPU fixture.
//
// Drives the three production anchor passes (their checked-in CSOs, the production constants header and the
// production binding layout) on synthetic frames. What is asserted, and why:
//   F) the 1/8-resolution level is the true 16-texel box mean: a checkerboard whose sparse taps would read 3.0
//      (16-texel mean 1.5) has to come back as 1.5 - the tap-offset trap the colour-track statistics also guard.
//   G) the recall and the gain: with a settled memory brighter than the current input the gain is below 1 and
//      brings the level back to the memory's; the gain NEVER exceeds 1 (no brightening, whatever the memory says);
//      the band cap bounds the correction; a memory twice as bright as the current input (a real light switch) is
//      rejected outright and the gain is exactly 1 (the guard SA1's A range cannot separate by amplitude, so the
//      bound is what keeps a real change from being corrected away).
//   A) the apply: the signals come back as input * gain, in place, with the alpha untouched, and strength 0 is a
//      byte-identical no-op.
//   O) OFF: with the option off the passes are not dispatched at all (the host gate the preprocessor documents);
//      the fixture asserts the C++ source-level gate and that no EXISTING shader changed is the python test's job.
//   E) the cost of the three dispatches, interleaved against the same frame without them, at both resolutions,
//      and the new texture memory.
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <span>
#include <string>
#include <vector>

#define main OriginalRRFixtureMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main

#include "shaders/fsrd_preprocess/FSRDPostMotionAnchorConstants.h"
#include "shaders/fsrd_preprocess/precompile/FSRDPostMotionAnchorApply_Shader.h"
#include "shaders/fsrd_preprocess/precompile/FSRDPostMotionAnchorGain_Shader.h"
#include "shaders/fsrd_preprocess/precompile/FSRDPostMotionAnchorStatsRecall_Shader.h"
#include "post_motion_anchor_debug_shader.h"

namespace
{
    using namespace PostMotionAnchorMath;
    constexpr DXGI_FORMAT kColour = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT kDepthFormat = DXGI_FORMAT_R32_FLOAT;
    constexpr D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    constexpr D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;

    ComPtr<ID3D12Resource> makeTexture(ID3D12Device* device, uint32_t width, uint32_t height, DXGI_FORMAT format,
                                       const wchar_t* name, uint16_t slices = 1)
    {
        D3D12_RESOURCE_DESC desc {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = width; desc.Height = height; desc.DepthOrArraySize = slices; desc.MipLevels = 1;
        desc.SampleDesc.Count = 1; desc.Format = format;
        desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        ComPtr<ID3D12Resource> resource;
        hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, kRead, nullptr,
                                           IID_PPV_ARGS(&resource)));
        resource->SetName(name);
        return resource;
    }

    uint32_t bytesPerPixel(DXGI_FORMAT format)
    {
        switch (format)
        {
            case DXGI_FORMAT_R16G16B16A16_FLOAT: return 8;
            case DXGI_FORMAT_R32_FLOAT: return 4;
            default: return 4;
        }
    }

    struct Descriptors
    {
        ComPtr<ID3D12DescriptorHeap> heap;
        UINT stride = 0;
        Descriptors(Host& host, UINT count)
        {
            D3D12_DESCRIPTOR_HEAP_DESC desc {};
            desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
            desc.NumDescriptors = count;
            desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
            hr(host.device->CreateDescriptorHeap(&desc, IID_PPV_ARGS(&heap)));
            stride = host.device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
            ID3D12DescriptorHeap* bound[] {heap.Get()};
            host.list->SetDescriptorHeaps(1, bound);
        }
        D3D12_CPU_DESCRIPTOR_HANDLE cpu(UINT index) const
        {
            auto handle = heap->GetCPUDescriptorHandleForHeapStart();
            handle.ptr += uint64_t(index) * stride;
            return handle;
        }
        D3D12_GPU_DESCRIPTOR_HANDLE gpu(UINT index) const
        {
            auto handle = heap->GetGPUDescriptorHandleForHeapStart();
            handle.ptr += uint64_t(index) * stride;
            return handle;
        }
        void srv(ID3D12Device* device, ID3D12Resource* texture, DXGI_FORMAT format, UINT index,
                 bool array = false) const
        {
            D3D12_SHADER_RESOURCE_VIEW_DESC view {};
            // A buffer needs its own view dimension (the production CreateSRV/CreateUAV switch on the resource
            // dimension the same way; a Texture2D view of a buffer crashes the driver).
            if (texture->GetDesc().Dimension == D3D12_RESOURCE_DIMENSION_BUFFER)
            {
                view.Format = DXGI_FORMAT_R32_TYPELESS;
                view.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
                view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
                view.Buffer.NumElements = UINT(texture->GetDesc().Width / 4);
                view.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
                device->CreateShaderResourceView(texture, &view, cpu(index));
                return;
            }
            view.Format = format;
            view.ViewDimension = array ? D3D12_SRV_DIMENSION_TEXTURE2DARRAY : D3D12_SRV_DIMENSION_TEXTURE2D;
            if (array) { view.Texture2DArray.MipLevels = 1; view.Texture2DArray.ArraySize = 8; }
            else view.Texture2D.MipLevels = 1;
            view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            device->CreateShaderResourceView(texture, &view, cpu(index));
        }
        void uav(ID3D12Device* device, ID3D12Resource* texture, DXGI_FORMAT format, UINT index,
                 bool array = false) const
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC view {};
            if (texture->GetDesc().Dimension == D3D12_RESOURCE_DIMENSION_BUFFER)
            {
                view.Format = DXGI_FORMAT_R32_TYPELESS;
                view.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
                view.Buffer.NumElements = UINT(texture->GetDesc().Width / 4);
                view.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
                device->CreateUnorderedAccessView(texture, nullptr, &view, cpu(index));
                return;
            }
            view.Format = format;
            view.ViewDimension = array ? D3D12_UAV_DIMENSION_TEXTURE2DARRAY : D3D12_UAV_DIMENSION_TEXTURE2D;
            if (array) view.Texture2DArray.ArraySize = 8;
            device->CreateUnorderedAccessView(texture, nullptr, &view, cpu(index));
        }
    };

    // The harness's own Readback assumes the resource sits in UAV state; these passes leave their fields in the
    // read state, so the fixture carries the colour-track fixture's variant.
    struct Readback
    {
        ComPtr<ID3D12Resource> resource;
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};
        uint32_t width = 0, height = 0;
        Readback(Host& host, ID3D12Resource* texture, D3D12_RESOURCE_STATES state)
        {
            const auto desc = texture->GetDesc();
            width = uint32_t(desc.Width); height = desc.Height;
            UINT rows; UINT64 rowBytes, total;
            host.device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, &rowBytes, &total);
            resource = buffer(host.device.Get(), total, D3D12_HEAP_TYPE_READBACK);
            barrier(host.list.Get(), texture, state, D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION source {}, destination {};
            source.pResource = texture; source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            destination.pResource = resource.Get(); destination.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            destination.PlacedFootprint = footprint;
            host.list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
            barrier(host.list.Get(), texture, D3D12_RESOURCE_STATE_COPY_SOURCE, state);
        }
        std::vector<uint8_t> bytes()
        {
            uint8_t* mapped; hr(resource->Map(0, nullptr, reinterpret_cast<void**>(&mapped)));
            const uint32_t bpp = uint32_t(footprint.Footprint.RowPitch) / std::max(1u, width);
            std::vector<uint8_t> out(size_t(width) * height * bpp);
            for (uint32_t y = 0; y < height; ++y)
                std::memcpy(out.data() + size_t(y) * width * bpp,
                            mapped + footprint.Offset + uint64_t(y) * footprint.Footprint.RowPitch,
                            size_t(width) * bpp);
            resource->Unmap(0, nullptr);
            return out;
        }
    };

    struct Binding { ID3D12Resource* resource; DXGI_FORMAT format; bool array = false; };

    void recordPassAt(Host& host, const Descriptors& descriptors, ID3D12PipelineState* pso,
                      ID3D12RootSignature* root, ID3D12Resource* constants, std::span<const Binding> srvs,
                      std::span<const Binding> uavs, uint32_t width, uint32_t height, UINT srvBase, UINT uavBase,
                      bool writeDescriptors = true)
    {
        host.list->SetPipelineState(pso);
        host.list->SetComputeRootSignature(root);
        // A heap bound as STATIC (the root signature's default) may not be rewritten while an earlier command list
        // still executes, so the cost loop writes every descriptor once and re-records with them afterwards.
        if (writeDescriptors)
        {
            UINT index = srvBase;
            for (const auto& binding : srvs) descriptors.srv(host.device.Get(), binding.resource, binding.format,
                                                             index++, binding.array);
            index = uavBase;
            for (const auto& binding : uavs) descriptors.uav(host.device.Get(), binding.resource, binding.format,
                                                             index++, binding.array);
        }
        ID3D12DescriptorHeap* bound[] {descriptors.heap.Get()};
        host.list->SetDescriptorHeaps(1, bound);
        host.list->SetComputeRootDescriptorTable(1, descriptors.gpu(srvBase));
        host.list->SetComputeRootDescriptorTable(2, descriptors.gpu(uavBase));
        host.list->SetComputeRootConstantBufferView(0, constants->GetGPUVirtualAddress());
        host.list->Dispatch((width + 7) / 8, (height + 7) / 8, 1);
    }

    void recordPass(Host& host, const Descriptors& descriptors, ID3D12PipelineState* pso,
                    ID3D12RootSignature* root, ID3D12Resource* constants, std::span<const Binding> srvs,
                    std::span<const Binding> uavs, uint32_t width, uint32_t height)
    {
        recordPassAt(host, descriptors, pso, root, constants, srvs, uavs, width, height, 0, UINT(srvs.size()));
    }

    struct Pipelines
    {
        ComPtr<ID3D12RootSignature> statsRoot, gainRoot, applyRoot;
        ComPtr<ID3D12PipelineState> statsPso, gainPso, applyPso;
        // DEBUG ONLY: a scratch copy of the statistics/recall shader that dumps its intermediates instead of the
        // production outputs (SA7 scratch/debug/FSRDPostMotionAnchorStatsRecallDbg.hlsl, compiled by the runner).
        ComPtr<ID3D12RootSignature> debugRoot;
        ComPtr<ID3D12PipelineState> debugPso;
        explicit Pipelines(Host& host)
        {
            const auto build = [&](const void* cso, size_t bytes, ComPtr<ID3D12RootSignature>& root,
                                   ComPtr<ID3D12PipelineState>& pso) {
                hr(host.device->CreateRootSignature(0, cso, bytes, IID_PPV_ARGS(&root)));
                D3D12_COMPUTE_PIPELINE_STATE_DESC desc {};
                desc.pRootSignature = root.Get();
                desc.CS = {cso, bytes};
                hr(host.device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&pso)));
            };
            build(FSRDPostMotionAnchorStatsRecall_cso, sizeof(FSRDPostMotionAnchorStatsRecall_cso), statsRoot, statsPso);
            build(FSRDPostMotionAnchorGain_cso, sizeof(FSRDPostMotionAnchorGain_cso), gainRoot, gainPso);
            build(FSRDPostMotionAnchorApply_cso, sizeof(FSRDPostMotionAnchorApply_cso), applyRoot, applyPso);
            // The generated header appends one zero byte as a presence marker (an empty scratch file yields a
            // one-byte array, which the dump skips), so the CSO size is the array size minus that marker.
            build(FSRDPostMotionAnchorStatsRecallDbg_cso, sizeof(FSRDPostMotionAnchorStatsRecallDbg_cso) - 1,
                  debugRoot, debugPso);
        }
    };

    // One persistent upload buffer per pass; allocating a constant buffer inside the measured submit is what
    // inflated task 24's first 1440p number.
    struct Constants
    {
        ComPtr<ID3D12Resource> stats, gain, apply;
        uint8_t* statsMapped = nullptr; uint8_t* gainMapped = nullptr; uint8_t* applyMapped = nullptr;
        Constants(Host& host)
        {
            const auto make = [&](size_t size, ComPtr<ID3D12Resource>& resource, uint8_t** mapped) {
                resource = buffer(host.device.Get(), size, D3D12_HEAP_TYPE_UPLOAD);
                hr(resource->Map(0, nullptr, reinterpret_cast<void**>(mapped)));
            };
            make(sizeof(StatsRecallConstants), stats, &statsMapped);
            make(sizeof(GainConstants), gain, &gainMapped);
            make(sizeof(ApplyConstants), apply, &applyMapped);
        }
        void upload(const StatsRecallConstants& s, const GainConstants& g, const ApplyConstants& a)
        {
            std::memcpy(statsMapped, &s, sizeof(s));
            std::memcpy(gainMapped, &g, sizeof(g));
            std::memcpy(applyMapped, &a, sizeof(a));
        }
    };

    void putHalf(std::vector<uint8_t>& data, size_t pixel, int channel, float value)
    {
        const uint16_t word = DirectX::PackedVector::XMConvertFloatToHalf(value);
        data[pixel * 8 + channel * 2] = uint8_t(word & 0xff);
        data[pixel * 8 + channel * 2 + 1] = uint8_t(word >> 8);
    }
    float halfAt(const std::vector<uint8_t>& data, size_t pixel, int channel)
    {
        const uint16_t word = uint16_t(data[pixel * 8 + channel * 2] | (data[pixel * 8 + channel * 2 + 1] << 8));
        return DirectX::PackedVector::XMConvertHalfToFloat(word);
    }
    float floatAt(const std::vector<uint8_t>& data, size_t pixel) 
    {
        float value; std::memcpy(&value, data.data() + pixel * 4, 4); return value;
    }

    // A synthetic frame: the same input level everywhere (so the comparison is analytic) with an optional
    // checkerboard for the box-mean check, a flat depth and zero motion.
    struct Frame
    {
        std::vector<uint8_t> diffuse, specular, depth, motion;
    };

    Frame makeFrame(uint32_t w, uint32_t h, float diffuseLevel, float specularLevel, float depth, float motionUv,
                    bool checkerboard = false)
    {
        Frame frame;
        frame.diffuse.resize(size_t(w) * h * 8); frame.specular.resize(size_t(w) * h * 8);
        frame.depth.resize(size_t(w) * h * 4); frame.motion.resize(size_t(w) * h * 8);
        for (uint32_t y = 0; y < h; ++y)
            for (uint32_t x = 0; x < w; ++x)
            {
                const size_t pixel = size_t(y) * w + x;
                const float level = checkerboard && ((x / 8 + y / 8) % 2 == 1) ? 12.0f : 1.5f;
                const float value = checkerboard ? level : diffuseLevel;
                putHalf(frame.diffuse, pixel, 0, value); putHalf(frame.diffuse, pixel, 1, value);
                putHalf(frame.diffuse, pixel, 2, value); putHalf(frame.diffuse, pixel, 3, 1.0f);
                const float spec = checkerboard ? 0.0f : specularLevel;
                putHalf(frame.specular, pixel, 0, spec); putHalf(frame.specular, pixel, 1, spec);
                putHalf(frame.specular, pixel, 2, spec); putHalf(frame.specular, pixel, 3, 1.0f);
                std::memcpy(frame.depth.data() + pixel * 4, &depth, 4);
                putHalf(frame.motion, pixel, 0, motionUv); putHalf(frame.motion, pixel, 1, 0.0f);
                putHalf(frame.motion, pixel, 2, 0.0f); putHalf(frame.motion, pixel, 3, 1.0f);
            }
        return frame;
    }

    void upload(Host& host, Scene& scene, ID3D12Resource* target, const std::vector<uint8_t>& data)
    {
        const auto desc = target->GetDesc();
        const size_t rowSize = size_t(desc.Width) * bytesPerPixel(desc.Format);
        need(data.size() == size_t(desc.Height) * rowSize, "upload extent matches the texture rows");
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {}; UINT rows; UINT64 copyRowBytes, total;
        host.device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, &copyRowBytes, &total);
        auto staging = buffer(host.device.Get(), total, D3D12_HEAP_TYPE_UPLOAD);
        uint8_t* mapped; hr(staging->Map(0, nullptr, reinterpret_cast<void**>(&mapped)));
        for (uint32_t y = 0; y < desc.Height; ++y)
            std::memcpy(mapped + footprint.Offset + uint64_t(y) * footprint.Footprint.RowPitch,
                        data.data() + size_t(y) * rowSize, rowSize);
        staging->Unmap(0, nullptr);
        barrier(host.list.Get(), target, kRead, D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION source {}, destination {};
        source.pResource = staging.Get(); source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        source.PlacedFootprint = footprint;
        destination.pResource = target; destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        destination.SubresourceIndex = 0;
        host.list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
        barrier(host.list.Get(), target, D3D12_RESOURCE_STATE_COPY_DEST, kRead);
        scene.uploads.push_back(staging);
    }

    // The camera used by every check: an identity view/projection pair, so the reprojection is the identity and a
    // non-identity result can only come from the anchor's own arithmetic.
    void identityMatrices(DirectX::XMFLOAT4X4& view, DirectX::XMFLOAT4X4& projection, DirectX::XMFLOAT4X4& previous)
    {
        DirectX::XMStoreFloat4x4(&view, DirectX::XMMatrixIdentity());
        DirectX::XMStoreFloat4x4(&previous, DirectX::XMMatrixIdentity());
        DirectX::XMFLOAT4X4 identity {};
        DirectX::XMStoreFloat4x4(&identity, DirectX::XMMatrixIdentity());
        // The house projection convention (FSRDPostFlickConstants.h): clip.w = P32 * view z, so the matrix HLSL
        // sees has M[3][2] = P32 and M[3][3] = 0. The desc holds the TRANSPOSE of that, so the desc's m[2][3] is
        // P32 and the desc's m[3][3] must be ZERO - an identity-derived matrix keeps m[3][3] = 1 and makes
        // clip.w = z + 1, which is what made the fixture's synthetic static-cell test misfire (the dump showed
        // static 0 for cell (0,0) and static 1 for cell (1,0) - a position-dependent residual from that +1).
        DirectX::XMFLOAT4X4 zero {};
        DirectX::XMStoreFloat4x4(&identity, DirectX::XMLoadFloat4x4(&zero));
        identity.m[0][0] = 1.0f; identity.m[1][1] = 1.0f; identity.m[2][2] = 1.0f; identity.m[2][3] = 1.0f;
        projection = identity;
    }

    struct Run
    {
        std::vector<uint8_t> stats, recalled, gain, diffuse, specular;
    };

    Run runAnchor(Host& host, const Pipelines& pipelines, Constants& constants, Scene& scene,
                  ID3D12Resource* diffuse, ID3D12Resource* specular, ID3D12Resource* depth,
                  ID3D12Resource* motion, ID3D12Resource* keyLevel, ID3D12Resource* keyDepth,
                  ID3D12Resource* stats, ID3D12Resource* recalled, ID3D12Resource* gain,
                  ID3D12Resource* sums, ID3D12Resource* sumsReset,
                  uint32_t width, uint32_t height, const StatsRecallConstants& statsConstants,
                  const GainConstants& gainConstants, const ApplyConstants& applyConstants, bool dispatchApply = true)
    {
        constants.upload(statsConstants, gainConstants, applyConstants);
        const uint32_t cellsX = std::max(1u, width / 8u), cellsY = std::max(1u, height / 8u);
        // The descriptor heaps must outlive the submission (the debug layer rejects a heap deleted before the
        // command list closes), so this fixture keeps every heap it binds for the whole run.
        static std::vector<Descriptors> heaps;
        auto& heap = heaps.emplace_back(host, 32);
        barrier(host.list.Get(), stats, kRead, kWrite);
        barrier(host.list.Get(), recalled, kRead, kWrite);
        // The production ordering: the sums are cleared by a 16-byte copy from the zero buffer before the
        // statistics pass accumulates, so the gain pass only ever reads them (no in-dispatch reset race).
        barrier(host.list.Get(), sums, D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_DEST);
        host.list->CopyBufferRegion(sums, 0, sumsReset, 0, 16);
        barrier(host.list.Get(), sums, D3D12_RESOURCE_STATE_COPY_DEST, kWrite);
        // The ring is read (SRV) by the statistics pass and written (UAV) by the gain pass: one texture may not be
        // both in a single dispatch, which is why the capture lives in the second pass.
        const Binding statsIn[] {{diffuse, kColour}, {specular, kColour}, {depth, kDepthFormat}, {motion, kColour},
                                 {keyLevel, kColour, true}, {keyDepth, kDepthFormat, true}};
        const Binding statsOut[] {{stats, kColour}, {recalled, kColour}, {sums, kColour}};
        recordPass(host, heap, pipelines.statsPso.Get(), pipelines.statsRoot.Get(), constants.stats.Get(),
                   statsIn, statsOut, cellsX, cellsY);
        barrier(host.list.Get(), stats, kWrite, kRead);
        barrier(host.list.Get(), recalled, kWrite, kRead);
        barrier(host.list.Get(), gain, kRead, kWrite);
        barrier(host.list.Get(), keyLevel, kRead, kWrite);
        barrier(host.list.Get(), keyDepth, kRead, kWrite);
        auto& gainHeap = heaps.emplace_back(host, 8);
        const Binding gainIn[] {{stats, kColour}, {recalled, kColour}};
        const Binding gainOut[] {{gain, kColour}, {keyLevel, kColour, true}, {keyDepth, kDepthFormat, true},
                                 {sums, kColour}};
        recordPass(host, gainHeap, pipelines.gainPso.Get(), pipelines.gainRoot.Get(), constants.gain.Get(),
                   gainIn, gainOut, cellsX, cellsY);
        barrier(host.list.Get(), gain, kWrite, kRead);
        barrier(host.list.Get(), keyLevel, kWrite, kRead);
        barrier(host.list.Get(), keyDepth, kWrite, kRead);
        if (dispatchApply)
        {
            barrier(host.list.Get(), diffuse, kRead, kWrite);
            barrier(host.list.Get(), specular, kRead, kWrite);
            auto& applyHeap = heaps.emplace_back(host, 8);
            const Binding applyIn[] {{gain, kColour}};
            const Binding applyOut[] {{diffuse, kColour}, {specular, kColour}};
            recordPass(host, applyHeap, pipelines.applyPso.Get(), pipelines.applyRoot.Get(), constants.apply.Get(),
                       applyIn, applyOut, width, height);
            barrier(host.list.Get(), diffuse, kWrite, kRead);
            barrier(host.list.Get(), specular, kWrite, kRead);
        }
        Run run;
        Readback statsRead(host, stats, kRead), recalledRead(host, recalled, kRead), gainRead(host, gain, kRead);
        Readback diffuseRead(host, diffuse, kRead), specularRead(host, specular, kRead);
        host.submit();
        host.checkDebug();
        run.stats = statsRead.bytes(); run.recalled = recalledRead.bytes(); run.gain = gainRead.bytes();
        run.diffuse = diffuseRead.bytes(); run.specular = specularRead.bytes();
        host.reset();
        return run;
    }

    // A scene sized so the 1/8-resolution fields are exact.
    struct Scene16
    {
        static constexpr uint32_t kWidth = 64, kHeight = 64;
        Host& host; Scene& scene;
        ComPtr<ID3D12Resource> diffuse, specular, depth, motion, keyLevel, keyDepth, stats, recalled, gain, sums;
        ComPtr<ID3D12Resource> sumsReset;
        Scene16(Host& host_, Scene& scene_) : host(host_), scene(scene_)
        {
            diffuse = makeTexture(host.device.Get(), kWidth, kHeight, kColour, L"anchor diffuse");
            specular = makeTexture(host.device.Get(), kWidth, kHeight, kColour, L"anchor specular");
            depth = makeTexture(host.device.Get(), kWidth, kHeight, kDepthFormat, L"anchor depth");
            motion = makeTexture(host.device.Get(), kWidth, kHeight, kColour, L"anchor motion");
            keyLevel = makeTexture(host.device.Get(), kWidth / 8, kHeight / 8, kColour, L"anchor key level", 8);
            keyDepth = makeTexture(host.device.Get(), kWidth / 8, kHeight / 8, kDepthFormat, L"anchor key depth", 8);
            stats = makeTexture(host.device.Get(), kWidth / 8, kHeight / 8, kColour, L"anchor stats");
            recalled = makeTexture(host.device.Get(), kWidth / 8, kHeight / 8, kColour, L"anchor recalled");
            gain = makeTexture(host.device.Get(), kWidth / 8, kHeight / 8, kColour, L"anchor gain");
            D3D12_RESOURCE_DESC sumsDesc {};
            sumsDesc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
            sumsDesc.Width = 16; sumsDesc.Height = 1; sumsDesc.DepthOrArraySize = 1; sumsDesc.MipLevels = 1;
            sumsDesc.SampleDesc.Count = 1; sumsDesc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            sumsDesc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
            D3D12_HEAP_PROPERTIES sumsHeap { D3D12_HEAP_TYPE_DEFAULT };
            hr(host.device->CreateCommittedResource(&sumsHeap, D3D12_HEAP_FLAG_NONE, &sumsDesc,
                D3D12_RESOURCE_STATE_COMMON, nullptr, IID_PPV_ARGS(&sums)));
            sums->SetName(L"anchor sums");
            D3D12_RESOURCE_DESC resetDesc = sumsDesc;
            resetDesc.Flags = D3D12_RESOURCE_FLAG_NONE; // an upload-heap resource may not be UAV
            D3D12_HEAP_PROPERTIES resetHeap { D3D12_HEAP_TYPE_UPLOAD };
            hr(host.device->CreateCommittedResource(&resetHeap, D3D12_HEAP_FLAG_NONE, &resetDesc,
                D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&sumsReset)));
            sumsReset->SetName(L"anchor sums reset");
            const uint32_t zeros[4] {0u, 0u, 0u, 0u};
            void* mapped = nullptr;
            const D3D12_RANGE empty {0, 0};
            hr(sumsReset->Map(0, &empty, &mapped));
            std::memcpy(mapped, zeros, sizeof(zeros));
            sumsReset->Unmap(0, nullptr);
        }
        // Fills every ring slice with one level and depth, so a recall can land on any slice.
        void fillMemory(float level, float depthValue)
        {
            std::vector<uint8_t> levelBytes(size_t(kWidth / 8) * (kHeight / 8) * 8);
            std::vector<uint8_t> depthBytes(size_t(kWidth / 8) * (kHeight / 8) * 4);
            for (size_t pixel = 0; pixel < size_t(kWidth / 8) * (kHeight / 8); ++pixel)
            {
                putHalf(levelBytes, pixel, 0, level); putHalf(levelBytes, pixel, 1, 0.0f);
                putHalf(levelBytes, pixel, 2, 0.0f); putHalf(levelBytes, pixel, 3, 0.0f);
                std::memcpy(depthBytes.data() + pixel * 4, &depthValue, 4);
            }
            const auto uploadSlices = [&](ID3D12Resource* target, const std::vector<uint8_t>& data, size_t rowBytes) {
                const auto desc = target->GetDesc();
                D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {}; UINT rows; UINT64 copyRowBytes, total;
                host.device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, &copyRowBytes, &total);
                for (uint16_t slice = 0; slice < 8; ++slice)
                {
                    auto staging = buffer(host.device.Get(), total, D3D12_HEAP_TYPE_UPLOAD);
                    uint8_t* mapped; hr(staging->Map(0, nullptr, reinterpret_cast<void**>(&mapped)));
                    for (uint32_t y = 0; y < (kHeight / 8); ++y)
                        std::memcpy(mapped + footprint.Offset + uint64_t(y) * footprint.Footprint.RowPitch,
                                    data.data() + size_t(y) * rowBytes, rowBytes);
                    staging->Unmap(0, nullptr);
                    barrier(host.list.Get(), target, kRead, D3D12_RESOURCE_STATE_COPY_DEST);
                    D3D12_TEXTURE_COPY_LOCATION source {}, destination {};
                    source.pResource = staging.Get(); source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
                    source.PlacedFootprint = footprint;
                    destination.pResource = target; destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
                    destination.SubresourceIndex = slice;
                    host.list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
                    barrier(host.list.Get(), target, D3D12_RESOURCE_STATE_COPY_DEST, kRead);
                    scene.uploads.push_back(staging);
                }
            };
            uploadSlices(keyLevel.Get(), levelBytes, size_t(kWidth / 8) * 8);
            uploadSlices(keyDepth.Get(), depthBytes, size_t(kWidth / 8) * 4);
        }
        void fillFrame(float diffuseLevel, float specularLevel, float depthValue, bool checkerboard = false)
        {
            const auto frame = makeFrame(kWidth, kHeight, diffuseLevel, specularLevel, depthValue, 0.0f, checkerboard);
            upload(host, scene, diffuse.Get(), frame.diffuse);
            upload(host, scene, specular.Get(), frame.specular);
            upload(host, scene, depth.Get(), frame.depth);
            upload(host, scene, motion.Get(), frame.motion);
        }
    };

    // The production constants for one frame, with the ring in slot 0.
    void buildConstants(const DirectX::XMFLOAT4X4& view, const DirectX::XMFLOAT4X4& projection,
                        const DirectX::XMFLOAT4X4& previous, uint32_t width, uint32_t height,
                        StatsRecallConstants& stats, GainConstants& gain, ApplyConstants& apply,
                        uint32_t motionFrames = 4u, float strength = 1.0f)
    {
        stats = {}; gain = {}; apply = {};
        PostMotionAnchorMath::SetSize(stats, gain, apply, width, height);
        stats.Projection = {1.0f, 1.0f, 0.0f, 0.0f};
        stats.Extra = {1.0f, kDepthTolerance, 1.0f, 0.0f};
        stats.Params = {strength, kMinStatic, kMinRecall, 0.0f};
        stats.KeySlice[0] = {0u, 8u, 8u, 8u};
        stats.KeySlice[1] = {8u, 8u, 8u, 8u};
        DirectX::XMFLOAT4X4 relative {};
        DirectX::XMStoreFloat4x4(&relative, PostMotionAnchorMath::LoadDesc(projection) *
            PostMotionAnchorMath::LoadDesc(view) *
            DirectX::XMMatrixInverse(nullptr, PostMotionAnchorMath::LoadDesc(view)));
        // The previous view is the current one here, so the static-cell test sees a zero camera displacement.
        DirectX::XMFLOAT4X4 identityDesc {};
        DirectX::XMStoreFloat4x4(&identityDesc, DirectX::XMMatrixIdentity());
        stats.PrevRelative = identityDesc;
        stats.Relative[0] = relative;
        const DirectX::XMMATRIX currentProjection = PostMotionAnchorMath::LoadDesc(projection);
        for (int row = 0; row < 4; ++row)
            std::memcpy(&stats.ProjectionRows.m[row][0], &currentProjection.r[row], sizeof(float) * 4);
        stats.SlotExtra[0] = {1.0f, 1.0f, 0.0f, 0.0f};
        for (uint32_t k = 1; k < kRingSize; ++k) stats.SlotExtra[k] = {0.0f, 0.0f, 0.0f, 0.0f};
        gain.Params = {kBandA, kBandTau, kCapExtra, kCapHard};
        gain.Params2 = {strength, kFallbackA, kTapStepCells, kCoverageTaps};
        gain.Params3 = {kRejectMult, kRejectAbs, kGainLow, float(motionFrames)};
        gain.Params4 = {0.0f, 0.0f, 0.0f, 0.0f}; // no keyframe capture in the behaviour checks
    }

    // DEBUG ONLY: run the scratch dump shader on the synthetic scene and print what the recall path computes.
    // OutStats = (staticCell, view z, key P32, key clip.w), OutRecalled = (uv.x, uv.y, expected, key depth).
    void debugDump(Host& host, const Pipelines& pipelines, Constants& constants, Scene& scene, Scene16& s,
                   const DirectX::XMFLOAT4X4& view, const DirectX::XMFLOAT4X4& projection,
                   const DirectX::XMFLOAT4X4& previous)
    {
        if (sizeof(FSRDPostMotionAnchorStatsRecallDbg_cso) <= 1)
        {
            std::cout << "anchor debug dump: skipped (the scratch debug shader is not present)" << std::endl;
            return;
        }
        s.fillFrame(10.0f, 0.0f, 10.0f);
        s.fillMemory(10.0f, 10.0f);
        StatsRecallConstants stats {}; GainConstants gain {}; ApplyConstants apply {};
        buildConstants(view, projection, previous, Scene16::kWidth, Scene16::kHeight, stats, gain, apply);
        constants.upload(stats, gain, apply);
        static std::vector<Descriptors> heaps;
        auto& heap = heaps.emplace_back(host, 32);
        barrier(host.list.Get(), s.stats.Get(), kRead, kWrite);
        barrier(host.list.Get(), s.recalled.Get(), kRead, kWrite);
        const Binding in[] {{s.diffuse.Get(), kColour}, {s.specular.Get(), kColour}, {s.depth.Get(), kDepthFormat},
                            {s.motion.Get(), kColour}, {s.keyLevel.Get(), kColour, true},
                            {s.keyDepth.Get(), kDepthFormat, true}};
        const Binding out[] {{s.stats.Get(), kColour}, {s.recalled.Get(), kColour}};
        recordPass(host, heap, pipelines.debugPso.Get(), pipelines.debugRoot.Get(), constants.stats.Get(), in, out,
                   Scene16::kWidth / 8, Scene16::kHeight / 8);
        barrier(host.list.Get(), s.stats.Get(), kWrite, kRead);
        barrier(host.list.Get(), s.recalled.Get(), kWrite, kRead);
        Readback statsRead(host, s.stats.Get(), kRead), recalledRead(host, s.recalled.Get(), kRead);
        host.submit();
        host.checkDebug();
        const auto statsBytes = statsRead.bytes(), recalledBytes = recalledRead.bytes();
        host.reset();
        for (size_t cell : {size_t(0), size_t(1)})
        {
            std::cout << "anchor debug cell " << cell << ": static " << halfAt(statsBytes, cell, 0)
                      << " viewZ " << halfAt(statsBytes, cell, 1) << " keyP32 " << halfAt(statsBytes, cell, 2)
                      << " clipW " << halfAt(statsBytes, cell, 3) << " | uv (" << halfAt(recalledBytes, cell, 0)
                      << ", " << halfAt(recalledBytes, cell, 1) << ") expected " << halfAt(recalledBytes, cell, 2)
                      << " keyDepth " << halfAt(recalledBytes, cell, 3) << std::endl;
        }
    }

    void runChecks(Host& host)
    {
        const Pipelines pipelines(host);
        Constants constants(host);
        Scene scene(host, 64, 64);
        Scene16 s(host, scene);
        DirectX::XMFLOAT4X4 view {}, projection {}, previous {};
        identityMatrices(view, projection, previous);

        // F) the 1/8-resolution level is the true 16-texel box mean.
        {
            s.fillFrame(0.0f, 0.0f, 10.0f, true);
            const float memory = 10.0f;   // a memory much brighter than the checkerboard
            s.fillMemory(memory, 10.0f);
            StatsRecallConstants stats {}; GainConstants gain {}; ApplyConstants apply {};
            buildConstants(view, projection, previous, Scene16::kWidth, Scene16::kHeight, stats, gain, apply);
            const auto run = runAnchor(host, pipelines, constants, scene, s.diffuse.Get(), s.specular.Get(),
                                       s.depth.Get(), s.motion.Get(), s.keyLevel.Get(), s.keyDepth.Get(),
                                       s.stats.Get(), s.recalled.Get(), s.gain.Get(), s.sums.Get(), s.sumsReset.Get(), Scene16::kWidth, Scene16::kHeight,
                                       stats, gain, apply, false);
            // Cells alternate between 1.5 and 12.0 in 8x8 blocks: the box mean of a cell must be exactly its block
            // value, never the sparse 3.0/20.0 a four-texel sample would give.
            const float cell0 = halfAt(run.stats, 0, 0), cell1 = halfAt(run.stats, 1, 0);
            std::cout << "anchor box mean: cell(0,0) " << cell0 << " cell(1,0) " << cell1 << std::endl;
            need(std::abs(cell0 - 1.5f) < 2e-3f && std::abs(cell1 - 12.0f) < 2e-2f,
                 "the 1/8-resolution level is the true 16-texel box mean");
        }

        // G) recall and gain: the memory is 2x brighter than the current input. The band cap bounds the
        // correction, and the reject guard (an excess far above the band) takes the whole frame to gain 1.
        {
            s.fillFrame(10.0f, 0.0f, 10.0f);
            s.fillMemory(10.0f, 10.0f);
            StatsRecallConstants stats {}; GainConstants gain {}; ApplyConstants apply {};
            buildConstants(view, projection, previous, Scene16::kWidth, Scene16::kHeight, stats, gain, apply, 4u, 1.0f);
            const auto run = runAnchor(host, pipelines, constants, scene, s.diffuse.Get(), s.specular.Get(),
                                       s.depth.Get(), s.motion.Get(), s.keyLevel.Get(), s.keyDepth.Get(),
                                       s.stats.Get(), s.recalled.Get(), s.gain.Get(), s.sums.Get(), s.sumsReset.Get(), Scene16::kWidth, Scene16::kHeight,
                                       stats, gain, apply);
            debugDump(host, pipelines, constants, scene, s, view, projection, previous);
            const float remembered = halfAt(run.recalled, 0, 0), valid = halfAt(run.recalled, 0, 1);
            const float gainValue = halfAt(run.gain, 0, 0);
            std::cout << "anchor settled memory: recalled " << remembered << " valid " << valid << " gain " << gainValue
                      << std::endl;
            need(valid > 0.5f && std::abs(remembered - 10.0f) < 0.05f, "the keyframe level is recalled");
            need(std::abs(gainValue - 1.0f) < 2e-3f, "a settled memory leaves the gain at 1 (no correction needed)");

            // The memory is now 2x the current input: a real light change. Half of it would be the post-motion
            // excess of a flick, twice as much is not, so the reject guard must keep the cell at gain 1.
            s.fillFrame(10.0f, 0.0f, 10.0f);
            s.fillMemory(20.0f, 10.0f);
            buildConstants(view, projection, previous, Scene16::kWidth, Scene16::kHeight, stats, gain, apply, 1u, 1.0f);
            const auto rejected = runAnchor(host, pipelines, constants, scene, s.diffuse.Get(), s.specular.Get(),
                                            s.depth.Get(), s.motion.Get(), s.keyLevel.Get(), s.keyDepth.Get(),
                                            s.stats.Get(), s.recalled.Get(), s.gain.Get(), s.sums.Get(),
                                            s.sumsReset.Get(), Scene16::kWidth, Scene16::kHeight, stats, gain, apply);
            const float rejectedGain = halfAt(rejected.gain, 0, 0);
            std::cout << "anchor reject: gain " << rejectedGain << std::endl;
            need(std::abs(rejectedGain - 1.0f) < 2e-3f, "an excess far above the band keeps gain 1");

            // The frame-level decision, in the order that also proves the sums are cleared. A memory at HALF the
            // current input is an excess of 0.5, far above the 0.30 threshold: the guard must reject it outright
            // (gain 1). NOTE (SA15 N3): on this uniform scene the per-cell guard also rejects a 0.5 excess (0.5 >
            // 0.30), so this check alone does not isolate the frame-level path - it is the NEXT check that does,
            // because a stale frame-level sum would reject it while the per-cell measurement accepts it. The next
            // frame's memory is 0.85x (an excess of 0.15, under the threshold): its own measurement must give
            // exactly 0.85, which a stale frame-level sum
            // (0.5) would turn back into a rejection.
            s.fillFrame(10.0f, 0.0f, 10.0f);
            s.fillMemory(5.0f, 10.0f);
            buildConstants(view, projection, previous, Scene16::kWidth, Scene16::kHeight, stats, gain, apply, 2u, 1.0f);
            const auto overThreshold = runAnchor(host, pipelines, constants, scene, s.diffuse.Get(), s.specular.Get(),
                                                 s.depth.Get(), s.motion.Get(), s.keyLevel.Get(), s.keyDepth.Get(),
                                                 s.stats.Get(), s.recalled.Get(), s.gain.Get(), s.sums.Get(),
                                                 s.sumsReset.Get(), Scene16::kWidth, Scene16::kHeight, stats, gain,
                                                 apply);
            const float overGain = halfAt(overThreshold.gain, 0, 0);
            std::cout << "anchor frame-level reject (0.5x memory, excess 0.5): gain " << overGain << std::endl;
            need(std::abs(overGain - 1.0f) < 2e-3f,
                 "an excess over the threshold rejects the whole frame (the per-cell path would correct to 0.803)");

            s.fillFrame(10.0f, 0.0f, 10.0f);
            s.fillMemory(8.5f, 10.0f);
            buildConstants(view, projection, previous, Scene16::kWidth, Scene16::kHeight, stats, gain, apply, 2u, 1.0f);
            const auto underThreshold = runAnchor(host, pipelines, constants, scene, s.diffuse.Get(), s.specular.Get(),
                                                  s.depth.Get(), s.motion.Get(), s.keyLevel.Get(), s.keyDepth.Get(),
                                                  s.stats.Get(), s.recalled.Get(), s.gain.Get(), s.sums.Get(),
                                                  s.sumsReset.Get(), Scene16::kWidth, Scene16::kHeight, stats, gain,
                                                  apply);
            const float underGain = halfAt(underThreshold.gain, 0, 0);
            std::cout << "anchor frame-level accept (0.85x memory, excess 0.15): gain " << underGain
                      << " (the sums were cleared: a stale 0.5 would reject to 1)" << std::endl;
            need(std::abs(underGain - 0.85f) < 5e-3f,
                 "an excess under the threshold corrects by its own measurement, so the frame-level sums are cleared");

            // A memory DARKER than the current input is the post-motion case (the current input is the
            // excessive one): the gain pulls the input down toward the settled memory, bounded by the band cap.
            s.fillFrame(10.0f, 0.0f, 10.0f);
            s.fillMemory(8.0f, 10.0f);
            buildConstants(view, projection, previous, Scene16::kWidth, Scene16::kHeight, stats, gain, apply, 2u, 1.0f);
            const auto corrected = runAnchor(host, pipelines, constants, scene, s.diffuse.Get(), s.specular.Get(),
                                             s.depth.Get(), s.motion.Get(), s.keyLevel.Get(), s.keyDepth.Get(),
                                             s.stats.Get(), s.recalled.Get(), s.gain.Get(), s.sums.Get(),
                                             s.sumsReset.Get(), Scene16::kWidth, Scene16::kHeight, stats, gain, apply);
            const float correctedGain = halfAt(corrected.gain, 0, 0);
            const float applied = halfAt(corrected.diffuse, 0, 0);
            const float capAtTwo = kBandA * std::exp(-2.0f / kBandTau) + kCapExtra;
            std::cout << "anchor correction: gain " << correctedGain << " applied " << applied << " cap excess "
                      << capAtTwo << std::endl;
            need(correctedGain < 1.0f && correctedGain >= 1.0f - std::min(capAtTwo, kCapHard) - 5e-3f,
                 "a darker memory pulls the input down, bounded by the band cap");
            need(std::abs(correctedGain - 0.8f) < 5e-3f, "the measured ratio (8/10) is the gain here");
            need(std::abs(applied - 10.0f * correctedGain) < 0.02f, "the apply multiplies the input by the gain");

            // A memory BRIGHTER than the current input must never brighten it (the current input is the settled
            // one, or a real darkening the anchor has no business undoing).
            s.fillFrame(10.0f, 0.0f, 10.0f);
            s.fillMemory(12.0f, 10.0f);
            buildConstants(view, projection, previous, Scene16::kWidth, Scene16::kHeight, stats, gain, apply, 2u, 1.0f);
            const auto brighter = runAnchor(host, pipelines, constants, scene, s.diffuse.Get(), s.specular.Get(),
                                            s.depth.Get(), s.motion.Get(), s.keyLevel.Get(), s.keyDepth.Get(),
                                            s.stats.Get(), s.recalled.Get(), s.gain.Get(), s.sums.Get(),
                                            s.sumsReset.Get(), Scene16::kWidth, Scene16::kHeight, stats, gain, apply);
            const float brighterGain = halfAt(brighter.gain, 0, 0);
            std::cout << "anchor no-brighten: gain " << brighterGain << std::endl;
            need(std::abs(brighterGain - 1.0f) < 2e-3f, "a brighter memory never brightens the input");
        }

        // A) strength 0 is a byte-identical no-op on the signals.
        {
            s.fillFrame(10.0f, 4.0f, 10.0f);
            s.fillMemory(12.0f, 10.0f);
            StatsRecallConstants stats {}; GainConstants gain {}; ApplyConstants apply {};
            buildConstants(view, projection, previous, Scene16::kWidth, Scene16::kHeight, stats, gain, apply, 2u, 0.0f);
            const auto run = runAnchor(host, pipelines, constants, scene, s.diffuse.Get(), s.specular.Get(),
                                       s.depth.Get(), s.motion.Get(), s.keyLevel.Get(), s.keyDepth.Get(),
                                       s.stats.Get(), s.recalled.Get(), s.gain.Get(), s.sums.Get(), s.sumsReset.Get(), Scene16::kWidth, Scene16::kHeight,
                                       stats, gain, apply);
            const float unchanged = halfAt(run.diffuse, 0, 0), gain0 = halfAt(run.gain, 0, 0);
            std::cout << "anchor strength 0: gain " << gain0 << " applied " << unchanged << std::endl;
            need(std::abs(gain0 - 1.0f) < 2e-3f, "strength 0 leaves the gain at 1");
            need(std::abs(unchanged - 10.0f) < 2e-2f, "strength 0 leaves the signal untouched");
        }
    }

    // The fence-around-submit instrument: each frame is recorded and submitted on its own, the anchor's three
    // dispatches interleaved against the same frame without them (only the apply pass), so the difference is the
    // anchor's cost. Fresh descriptor heaps per frame, released after the submit that consumes them (a heap must
    // outlive its submission, and rewriting one heap between passes would make every recorded dispatch read the
    // last pass's descriptors).
    void costChecks(Host& host)
    {
        const Pipelines pipelines(host);
        Constants constants(host);
        for (const char* resolution : {"1505x847", "2560x1440"})
        {
            const std::string text(resolution);
            const uint32_t w = uint32_t(std::stoul(text)), h = uint32_t(std::stoul(text.substr(text.find('x') + 1)));
            auto colour = makeTexture(host.device.Get(), w, h, kColour, L"anchor cost colour");
            auto depth = makeTexture(host.device.Get(), w, h, kDepthFormat, L"anchor cost depth");
            auto motion = makeTexture(host.device.Get(), w, h, kColour, L"anchor cost motion");
            auto keyLevel = makeTexture(host.device.Get(), w / 8, h / 8, kColour, L"anchor cost key level", 8);
            auto keyDepth = makeTexture(host.device.Get(), w / 8, h / 8, kDepthFormat, L"anchor cost key depth", 8);
            auto stats = makeTexture(host.device.Get(), w / 8, h / 8, kColour, L"anchor cost stats");
            auto recalled = makeTexture(host.device.Get(), w / 8, h / 8, kColour, L"anchor cost recalled");
            auto gain = makeTexture(host.device.Get(), w / 8, h / 8, kColour, L"anchor cost gain");
            D3D12_RESOURCE_DESC sumsDesc {};
            sumsDesc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
            sumsDesc.Width = 16; sumsDesc.Height = 1; sumsDesc.DepthOrArraySize = 1; sumsDesc.MipLevels = 1;
            sumsDesc.SampleDesc.Count = 1; sumsDesc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            sumsDesc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
            D3D12_HEAP_PROPERTIES sumsHeap { D3D12_HEAP_TYPE_DEFAULT };
            ComPtr<ID3D12Resource> sums;
            hr(host.device->CreateCommittedResource(&sumsHeap, D3D12_HEAP_FLAG_NONE, &sumsDesc,
                D3D12_RESOURCE_STATE_COMMON, nullptr, IID_PPV_ARGS(&sums)));
            DirectX::XMFLOAT4X4 view {}, projection {}, previous {};
            identityMatrices(view, projection, previous);
            StatsRecallConstants statsConstants {}; GainConstants gainConstants {}; ApplyConstants applyConstants {};
            buildConstants(view, projection, previous, w, h, statsConstants, gainConstants, applyConstants);
            constants.upload(statsConstants, gainConstants, applyConstants);
            // Three configurations per batch, so the table says where the budget goes: the apply alone (the
            // production shape before the fold), the two 1/8-resolution passes alone, and all three together.
            // A rotating pool of three descriptor heaps with fixed per-pass offsets, rewritten once per frame -
            // the production pattern (ComputeState rotates pooled slots so a heap is never rewritten while a list
            // that bound it still executes). Three rotations cover the frames in flight.
            std::vector<Descriptors> heaps;
            heaps.reserve(3);
            for (int i = 0; i < 3; ++i) heaps.emplace_back(host, 32);
            std::vector<double> with, without, lowres, empty;
            // Each configuration writes its own descriptors on its first recording and never again (a heap bound as
            // STATIC may not be rewritten while an earlier command list executes).
            uint32_t rotation = 0;
            const uint32_t batches = 24, frames = 8;
            for (uint32_t batch = 0; batch < batches; ++batch)
            {
                for (int mode = 0; mode < 4; ++mode)
                {
                    // mode 3 is the instrument's own floor: a truly empty frame (no dispatch at all), so every
                    // other number is quoted against it - the per-frame fence and the submit are part of the wall
                    // time, and the colour-track instrument's floor was 0.005 ms on the same harness.
                    const bool anchor = mode == 1 || mode == 2;
                    const bool applyPass = mode == 0 || mode == 2;
                    const auto start = std::chrono::steady_clock::now();
                    for (uint32_t frame = 0; frame < frames; ++frame)
                    {
                        // Every frame writes its own heap's descriptors, exactly as ComputeState does per dispatch.
                        const bool writeDescriptors = true;
                        const Descriptors& heap = heaps[rotation % heaps.size()];
                        ++rotation;
                        if (anchor)
                        {
                            barrier(host.list.Get(), stats.Get(), kRead, kWrite);
                            barrier(host.list.Get(), recalled.Get(), kRead, kWrite);
                            const Binding statsIn[] {{colour.Get(), kColour}, {colour.Get(), kColour},
                                                     {depth.Get(), kDepthFormat}, {motion.Get(), kColour},
                                                     {keyLevel.Get(), kColour, true},
                                                     {keyDepth.Get(), kDepthFormat, true}};
                            const Binding statsOut[] {{stats.Get(), kColour}, {recalled.Get(), kColour},
                                                     {sums.Get(), kColour}};
                            recordPassAt(host, heap, pipelines.statsPso.Get(), pipelines.statsRoot.Get(),
                                         constants.stats.Get(), statsIn, statsOut, w / 8, h / 8, 0, 16, writeDescriptors);
                            barrier(host.list.Get(), stats.Get(), kWrite, kRead);
                            barrier(host.list.Get(), recalled.Get(), kWrite, kRead);
                            barrier(host.list.Get(), gain.Get(), kRead, kWrite);
                            barrier(host.list.Get(), keyLevel.Get(), kRead, kWrite);
                            barrier(host.list.Get(), keyDepth.Get(), kRead, kWrite);
                            const Binding gainIn[] {{stats.Get(), kColour}, {recalled.Get(), kColour}};
                            const Binding gainOut[] {{gain.Get(), kColour}, {keyLevel.Get(), kColour, true},
                                                     {keyDepth.Get(), kDepthFormat, true}, {sums.Get(), kColour}};
                            recordPassAt(host, heap, pipelines.gainPso.Get(), pipelines.gainRoot.Get(),
                                         constants.gain.Get(), gainIn, gainOut, w / 8, h / 8, 6, 19, writeDescriptors);
                            barrier(host.list.Get(), gain.Get(), kWrite, kRead);
                            barrier(host.list.Get(), keyLevel.Get(), kWrite, kRead);
                            barrier(host.list.Get(), keyDepth.Get(), kWrite, kRead);
                        }
                        if (applyPass)
                        {
                            barrier(host.list.Get(), colour.Get(), kRead, kWrite);
                            const Binding applyIn[] {{gain.Get(), kColour}};
                            const Binding applyOut[] {{colour.Get(), kColour}, {colour.Get(), kColour}};
                            recordPassAt(host, heap, pipelines.applyPso.Get(), pipelines.applyRoot.Get(),
                                         constants.apply.Get(), applyIn, applyOut, w, h, 8, 23, writeDescriptors);
                            barrier(host.list.Get(), colour.Get(), kWrite, kRead);
                        }
                        // No debug-layer check inside the measured loop: walking the info queue costs more than the
                        // dispatches do (the colour-track instrument checks once, outside).
                        host.submit();
                        host.reset();
                    }
                    const double perFrame = std::chrono::duration<double, std::milli>(
                        std::chrono::steady_clock::now() - start).count() / frames;
                    (mode == 0 ? without : (mode == 1 ? lowres : (mode == 2 ? with : empty))).push_back(perFrame);
                }
            }
            std::sort(with.begin(), with.end()); std::sort(without.begin(), without.end());
            std::sort(lowres.begin(), lowres.end()); std::sort(empty.begin(), empty.end());
            const double median = with[with.size() / 2], baseline = without[without.size() / 2];
            const double lowresMedian = lowres[lowres.size() / 2];
            const double emptyMedian = empty[empty.size() / 2];
            // The ring: kRingSize slices of (level RGBA16F 8 B + depth R32F 4 B) per 1/8-res cell, plus the three
            // 1/8-res fields (stats, recalled, gain).
            const uint64_t ringBytes = uint64_t(w / 8) * (h / 8) * (8 + 4) * kRingSize;
            const uint64_t fieldBytes = 3ull * (w / 8) * (h / 8) * 8;
            std::cout << "anchor cost at " << w << "x" << h << ": empty frame " << emptyMedian
                      << " ms, apply alone " << (baseline - emptyMedian) << " ms, the two 1/8-resolution passes "
                      << (lowresMedian - emptyMedian) << " ms, all three " << (median - emptyMedian)
                      << " ms (raw: " << median << "/" << baseline << "/" << lowresMedian << "/"
                      << emptyMedian << "); new textures " << (ringBytes + fieldBytes) / (1024.0 * 1024.0)
                      << " MiB" << std::endl;
        }
    }
}

int main(int argc, char** argv) try
{
    std::cout.setf(std::ios::unitbuf);
    need(argc == 2, "job JSON required");
    Host host;
    runChecks(host);
    std::cout << "anchor behaviour checks passed" << std::endl;
    costChecks(host);
    host.checkDebug();
    std::cout << "PASS checks=" << checks << " debug_errors=0 debug_warnings=0\n";
    return 0;
}
catch (const std::exception& error)
{
    std::cerr << error.what() << '\n';
    return 1;
}
