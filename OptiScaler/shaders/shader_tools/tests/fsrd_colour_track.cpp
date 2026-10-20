// Post-RR colour tracking (task 25 T2), GPU fixture.
//
// Runs the three production colour-track passes (their checked-in CSOs, the production constants header and the
// production binding layout) on synthetic frames, plus one dispatch of the production composition CSO against a
// copy of the BASE composition CSO compiled from f97d5d040. What is asserted, and why:
//   F) the quarter-res statistics are the true 16-texel box mean: a checkerboard whose four sparse taps would
//      read 3.0 (16-texel mean 1.5) has to come back as 1.5. This is the tap-offset bug the review found.
//   B) the chain moves the composite's chroma onto the tracked target while leaving every pixel's luminance
//      exactly RR's (colour only), and strength 0 returns the composite byte-identically.
//   C) the EMA: a colour step moves the output by the EMA weight, not all at once.
//   D) the MV/depth gate: a reprojection whose history depth disagrees beyond the tolerance, and one that warps
//      off screen, both restart from the current input colour instead of blending.
//   A) OFF identity: the production composition CSO with the colour-track flag off is byte-identical to the base
//      composition CSO on the same inputs; with the flag on the composite is still byte-identical and the target
//      texture receives RR's input colour in output units (the analytic value); with the flag off the bound
//      target texture is untouched.
//   E) the cost of the three dispatches, interleaved against the same frame without them, at both resolutions.
//
// The synthetic inputs use the PRODUCTION conventions: motion is the canonical UV displacement (not pixels), the
// normals texture is R10G10B10A2_UNORM with the octahedral pair in xy, the depth is the signed view-space depth.
// A fixture that hand-builds its own idea of those would validate the shader against itself (task 24, lesson 5).
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

#include "shaders/fsrd_preprocess/FSRDColourTrackConstants.h"
#include "shaders/fsrd_preprocess/precompile/FSRDColourTrackApply_Shader.h"
#include "shaders/fsrd_preprocess/precompile/FSRDColourTrackStats_Shader.h"
#include "shaders/fsrd_preprocess/precompile/FSRDColourTrackTrack_Shader.h"
#include "shaders/fsrd_preprocess/precompile/FSRDOutputComp_Shader.h"
#include "base_comp_shader.h"

namespace
{
    constexpr DXGI_FORMAT kColour = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT kDepth = DXGI_FORMAT_R32_FLOAT;
    constexpr DXGI_FORMAT kNormals = DXGI_FORMAT_R10G10B10A2_UNORM;
    constexpr DXGI_FORMAT kAlbedo = DXGI_FORMAT_R8G8B8A8_UNORM;
    constexpr D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    constexpr D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;

    // Mirrors FSRD::Composition::Constants (FSRDShaderData.h). The layout is pinned there by static_asserts, and
    // these repeat the two that matter here, so a drift stops this fixture instead of silently mis-binding.
    struct alignas(16) CompositionConstants
    {
        DirectX::XMFLOAT4 DstTexSize;
        uint32_t Flags;
        DirectX::XMUINT3 Padding;
        DirectX::XMFLOAT2 SourceUvScale;
        DirectX::XMFLOAT2 SourceUvOffset;
        float SpecularAlbedoDemodulation;
        float DiffuseAlbedoModulation;
        float UnsupportedAlbedoRecovery;
        float DemodDivisorFloor;
    };
    static_assert(sizeof(CompositionConstants) == 64, "composition constants layout");
    static_assert(offsetof(CompositionConstants, Flags) == 16, "composition flags offset");
    static_assert(offsetof(CompositionConstants, SpecularAlbedoDemodulation) == 48, "composition modulation offset");

    ComPtr<ID3D12Resource> makeTexture(ID3D12Device* device, uint32_t width, uint32_t height, DXGI_FORMAT format,
                                       const wchar_t* name)
    {
        D3D12_RESOURCE_DESC desc {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = width; desc.Height = height; desc.DepthOrArraySize = desc.MipLevels = 1;
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
            case DXGI_FORMAT_R32G32_FLOAT: return 8;
            case DXGI_FORMAT_R32_FLOAT: return 4;
            case DXGI_FORMAT_R10G10B10A2_UNORM: return 4;
            default: return 4;
        }
    }

    // Staging upload into an existing texture; the staging buffer is retained by the scene until the run ends.
    void uploadTexture(Host& host, Scene& scene, ID3D12Resource* target, const void* data, size_t bytes,
                       D3D12_RESOURCE_STATES state)
    {
        const auto desc = target->GetDesc();
        const uint32_t rowSize = uint32_t(desc.Width) * bytesPerPixel(desc.Format);
        if (bytes != size_t(desc.Height) * rowSize)
        {
            std::cerr << "upload extent mismatch: " << bytes << " bytes for a "
                      << desc.Width << "x" << desc.Height << " format " << unsigned(desc.Format)
                      << " texture needing " << size_t(desc.Height) * rowSize << " bytes" << std::endl;
        }
        need(bytes == size_t(desc.Height) * rowSize, "upload extent matches the texture rows");
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {}; UINT rows; UINT64 copyRowBytes, total;
        host.device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, &copyRowBytes, &total);
        auto staging = buffer(host.device.Get(), total, D3D12_HEAP_TYPE_UPLOAD);
        uint8_t* mapped; hr(staging->Map(0, nullptr, reinterpret_cast<void**>(&mapped)));
        for (uint32_t y = 0; y < desc.Height; ++y)
            std::memcpy(mapped + footprint.Offset + uint64_t(y) * footprint.Footprint.RowPitch,
                        static_cast<const uint8_t*>(data) + uint64_t(y) * rowSize, rowSize);
        staging->Unmap(0, nullptr);
        barrier(host.list.Get(), target, state, D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION source {}, destination {};
        source.pResource = staging.Get(); source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        source.PlacedFootprint = footprint;
        destination.pResource = target; destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        host.list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
        barrier(host.list.Get(), target, D3D12_RESOURCE_STATE_COPY_DEST, state);
        scene.uploads.push_back(staging);
    }

    struct Readback
    {
        ComPtr<ID3D12Resource> resource;
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};
        uint32_t width = 0, height = 0, bytesPerPixel = 0;
        Readback(Host& host, ID3D12Resource* texture, D3D12_RESOURCE_STATES state)
        {
            const auto desc = texture->GetDesc();
            width = uint32_t(desc.Width); height = desc.Height;
            bytesPerPixel = (desc.Format == kColour) ? 8u : (desc.Format == kDepth ? 4u : 4u);
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
            std::vector<uint8_t> out(size_t(width) * height * bytesPerPixel);
            for (uint32_t y = 0; y < height; ++y)
                std::memcpy(out.data() + size_t(y) * width * bytesPerPixel,
                            mapped + footprint.Offset + uint64_t(y) * footprint.Footprint.RowPitch,
                            size_t(width) * bytesPerPixel);
            resource->Unmap(0, nullptr);
            return out;
        }
    };

    float halfAt(const std::vector<uint8_t>& data, size_t pixel, int channel)
    {
        const uint16_t word = uint16_t(data[pixel * 8 + channel * 2] | (data[pixel * 8 + channel * 2 + 1] << 8));
        return DirectX::PackedVector::XMConvertHalfToFloat(word);
    }
    void putHalf(std::vector<uint8_t>& data, size_t pixel, int channel, float value)
    {
        const uint16_t word = DirectX::PackedVector::XMConvertFloatToHalf(value);
        data[pixel * 8 + channel * 2] = uint8_t(word & 0xff);
        data[pixel * 8 + channel * 2 + 1] = uint8_t(word >> 8);
    }
    float luminance(float r, float g, float b) { return 0.2126f * r + 0.7152f * g + 0.0722f * b; }
    float shareOf(const std::vector<uint8_t>& data, size_t pixel)
    {
        const float r = halfAt(data, pixel, 0), g = halfAt(data, pixel, 1), b = halfAt(data, pixel, 2);
        return r / std::max(r + g + b, 1e-6f);
    }

    // Descriptor heap for one recorded frame: SRVs then UAVs, kept alive until the submission completes.
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
        void srv(ID3D12Device* device, ID3D12Resource* texture, DXGI_FORMAT format, UINT index) const
        {
            D3D12_SHADER_RESOURCE_VIEW_DESC view {};
            view.Format = format; view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
            view.Texture2D.MipLevels = 1;
            view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            device->CreateShaderResourceView(texture, &view, cpu(index));
        }
        void uav(ID3D12Device* device, ID3D12Resource* texture, DXGI_FORMAT format, UINT index) const
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC view {};
            view.Format = format; view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            device->CreateUnorderedAccessView(texture, nullptr, &view, cpu(index));
        }
    };

    struct Binding { ID3D12Resource* resource; DXGI_FORMAT format; };

    void recordPass(Host& host, const Descriptors& descriptors, ID3D12PipelineState* pso,
                    ID3D12RootSignature* root, ID3D12Resource* constants,
                    std::span<const Binding> srvs, std::span<const Binding> uavs, uint32_t width, uint32_t height)
    {
        host.list->SetPipelineState(pso);
        host.list->SetComputeRootSignature(root);
        UINT index = 0;
        for (const auto& binding : srvs) descriptors.srv(host.device.Get(), binding.resource, binding.format, index++);
        for (const auto& binding : uavs) descriptors.uav(host.device.Get(), binding.resource, binding.format, index++);
        host.list->SetComputeRootDescriptorTable(1, descriptors.gpu(0));
        host.list->SetComputeRootDescriptorTable(2, descriptors.gpu(UINT(srvs.size())));
        host.list->SetComputeRootConstantBufferView(0, constants->GetGPUVirtualAddress());
        host.list->Dispatch((width + 7) / 8, (height + 7) / 8, 1);
    }

    struct Pipelines
    {
        ComPtr<ID3D12RootSignature> statsRoot, trackRoot, applyRoot, compRoot, baseRoot;
        ComPtr<ID3D12PipelineState> statsPso, trackPso, applyPso, compPso, basePso;
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
            build(FSRDColourTrackStats_cso, sizeof(FSRDColourTrackStats_cso), statsRoot, statsPso);
            build(FSRDColourTrackTrack_cso, sizeof(FSRDColourTrackTrack_cso), trackRoot, trackPso);
            build(FSRDColourTrackApply_cso, sizeof(FSRDColourTrackApply_cso), applyRoot, applyPso);
            build(FSRDOutputComp_cso, sizeof(FSRDOutputComp_cso), compRoot, compPso);
            build(BaseOutputComp_cso, sizeof(BaseOutputComp_cso), baseRoot, basePso);
        }
    };

    // One persistent upload buffer per pass: allocating a constant buffer inside the measured submit is what
    // inflated task 24's first 1440p number.
    struct Constants
    {
        ComPtr<ID3D12Resource> stats, track, apply;
        uint8_t* statsMapped = nullptr; uint8_t* trackMapped = nullptr; uint8_t* applyMapped = nullptr;
        Constants(Host& host)
        {
            const auto create = [&](ComPtr<ID3D12Resource>& resource, size_t bytes, uint8_t** mapped) {
                resource = buffer(host.device.Get(), (bytes + 255) & ~size_t(255), D3D12_HEAP_TYPE_UPLOAD);
                hr(resource->Map(0, nullptr, reinterpret_cast<void**>(mapped)));
            };
            create(stats, sizeof(ColourTrackMath::StatsConstants), &statsMapped);
            create(track, sizeof(ColourTrackMath::TrackConstants), &trackMapped);
            create(apply, sizeof(ColourTrackMath::ApplyConstants), &applyMapped);
        }
    };

    // The full three-pass chain on one frame. `motionUv` is the production canonical motion (previous UV minus
    // current UV); `depthDelta` is its z. The composite is corrected in place.
    void recordChain(Host& host, const Pipelines& pipelines, const Constants& constants,
                     std::vector<Descriptors>& heaps,
                     ID3D12Resource* colour, ID3D12Resource* input, ID3D12Resource* motion, ID3D12Resource* depth,
                     ID3D12Resource* normals, ID3D12Resource* stats, ID3D12Resource* target, ID3D12Resource* motionOut,
                     ID3D12Resource* gain, ID3D12Resource* historyRead, ID3D12Resource* historyWrite,
                     uint32_t width, uint32_t height, float emaWeight, float strength, float tapStep,
                     bool historyValid)
    {
        const uint32_t quarterW = std::max(1u, width / 4), quarterH = std::max(1u, height / 4);
        const ColourTrackMath::StatsConstants statsConstants {
            .Size = {float(width), float(height), float(quarterW), float(quarterH)}};
        std::memcpy(constants.statsMapped, &statsConstants, sizeof(statsConstants));
        const ColourTrackMath::TrackConstants trackConstants {
            .Size = {float(width), float(height), float(quarterW), float(quarterH)},
            .Params = {emaWeight, ColourTrackMath::kDepthTolerance, strength, historyValid ? 1.0f : 0.0f},
            .Params2 = {tapStep, 0.0f, 0.0f, 0.0f}};
        std::memcpy(constants.trackMapped, &trackConstants, sizeof(trackConstants));
        const ColourTrackMath::ApplyConstants applyConstants {
            .Size = {float(width), float(height), 1.0f / float(width), 1.0f / float(height)}};
        std::memcpy(constants.applyMapped, &applyConstants, sizeof(applyConstants));

        const Binding statsSrvs[] {{colour, kColour}, {input, kColour}, {motion, kColour}, {depth, kDepth},
                                   {normals, kNormals}};
        const Binding statsUavs[] {{stats, kColour}, {target, kColour}, {motionOut, kColour}};
        for (auto& resource : {stats, target, motionOut}) barrier(host.list.Get(), resource, kRead, kWrite);
        heaps.emplace_back(host, 8);
        recordPass(host, heaps.back(), pipelines.statsPso.Get(), pipelines.statsRoot.Get(), constants.stats.Get(),
                   statsSrvs, statsUavs, quarterW, quarterH);
        for (auto& resource : {stats, target, motionOut}) barrier(host.list.Get(), resource, kWrite, kRead);

        const Binding trackSrvs[] {{stats, kColour}, {target, kColour}, {motionOut, kColour}, {historyRead, kColour}};
        const Binding trackUavs[] {{gain, kColour}, {historyWrite, kColour}};
        for (auto& resource : {gain, historyWrite}) barrier(host.list.Get(), resource, kRead, kWrite);
        heaps.emplace_back(host, 6);
        recordPass(host, heaps.back(), pipelines.trackPso.Get(), pipelines.trackRoot.Get(), constants.track.Get(),
                   trackSrvs, trackUavs, quarterW, quarterH);
        for (auto& resource : {gain, historyWrite}) barrier(host.list.Get(), resource, kWrite, kRead);

        const Binding applySrvs[] {{gain, kColour}};
        const Binding applyUavs[] {{colour, kColour}};
        barrier(host.list.Get(), colour, kRead, kWrite);
        heaps.emplace_back(host, 2);
        recordPass(host, heaps.back(), pipelines.applyPso.Get(), pipelines.applyRoot.Get(), constants.apply.Get(),
                   applySrvs, applyUavs, width, height);
        barrier(host.list.Get(), colour, kWrite, kRead);
    }

    // ---- F) the statistics are the true 16-texel box mean ------------------------------------------------
    void statsChecks(Host& host, const Pipelines& pipelines, const Constants& constants)
    {
        constexpr uint32_t w = 64, h = 64;
        Scene scene(host, 8, 8);
        auto colour = makeTexture(host.device.Get(), w, h, kColour, L"ct stats colour");
        auto input = makeTexture(host.device.Get(), w, h, kColour, L"ct stats input");
        auto motion = makeTexture(host.device.Get(), w, h, kColour, L"ct stats motion");
        auto depth = makeTexture(host.device.Get(), w, h, kDepth, L"ct stats depth");
        auto normals = makeTexture(host.device.Get(), w, h, kNormals, L"ct stats normals");
        auto stats = makeTexture(host.device.Get(), w / 4, h / 4, kColour, L"ct stats out");
        auto target = makeTexture(host.device.Get(), w / 4, h / 4, kColour, L"ct stats target");
        auto motionOut = makeTexture(host.device.Get(), w / 4, h / 4, kColour, L"ct stats motion out");

        std::vector<uint8_t> colourData(size_t(w) * h * 8), inputData(size_t(w) * h * 8);
        std::vector<uint8_t> motionData(size_t(w) * h * 8, 0);
        std::vector<float> depthData(size_t(w) * h);
        std::vector<uint32_t> normalData(size_t(w) * h);
        for (uint32_t y = 0; y < h; ++y)
            for (uint32_t x = 0; x < w; ++x)
            {
                const size_t pixel = size_t(y) * w + x;
                // The four sparse taps of the pre-fix shader (x, y in {0, 2} of each 4x4 cell) all read 3.0 and
                // 20.0; the true 16-texel means are 1.5 and 12.5.
                const bool corner = (x % 2 == 0) && (y % 2 == 0);
                for (int channel = 0; channel < 3; ++channel) putHalf(colourData, pixel, channel, corner ? 3.0f : 1.0f);
                putHalf(colourData, pixel, 3, 1.0f);
                for (int channel = 0; channel < 3; ++channel) putHalf(inputData, pixel, channel, corner ? 6.0f : 2.0f);
                putHalf(inputData, pixel, 3, 1.0f);
                putHalf(motionData, pixel, 3, 1.0f);
                depthData[pixel] = corner ? 20.0f : 10.0f;
                normalData[pixel] = (512u << 0) | (512u << 10) | (0u << 20) | (0u << 30);
            }
        uploadTexture(host, scene, colour.Get(), colourData.data(), colourData.size(), kRead);
        uploadTexture(host, scene, input.Get(), inputData.data(), inputData.size(), kRead);
        uploadTexture(host, scene, motion.Get(), motionData.data(), motionData.size(), kRead);
        uploadTexture(host, scene, depth.Get(), depthData.data(), depthData.size() * sizeof(float), kRead);
        uploadTexture(host, scene, normals.Get(), normalData.data(), normalData.size() * sizeof(uint32_t), kRead);

        Descriptors descriptors(host, 8);
        const uint32_t quarterW = w / 4, quarterH = h / 4;
        const ColourTrackMath::StatsConstants statsConstants {
            .Size = {float(w), float(h), float(quarterW), float(quarterH)}};
        std::memcpy(constants.statsMapped, &statsConstants, sizeof(statsConstants));
        const Binding srvs[] {{colour.Get(), kColour}, {input.Get(), kColour}, {motion.Get(), kColour},
                              {depth.Get(), kDepth}, {normals.Get(), kNormals}};
        const Binding uavs[] {{stats.Get(), kColour}, {target.Get(), kColour}, {motionOut.Get(), kColour}};
        for (auto* resource : {stats.Get(), target.Get(), motionOut.Get()})
            barrier(host.list.Get(), resource, kRead, kWrite);
        recordPass(host, descriptors, pipelines.statsPso.Get(), pipelines.statsRoot.Get(), constants.stats.Get(),
                   srvs, uavs, quarterW, quarterH);
        for (auto* resource : {stats.Get(), target.Get(), motionOut.Get()})
            barrier(host.list.Get(), resource, kWrite, kRead);

        Readback read(host, stats.Get(), kRead);
        host.submit();
        host.checkDebug();
        auto data = read.bytes();   // the readback map must happen after the copy has executed
        const size_t centre = size_t(quarterH / 2) * quarterW + quarterW / 2;
        const float mean = halfAt(data, centre, 0);
        const float meanDepth = halfAt(data, centre, 3);
        std::cout << "colour-track stats: box mean " << mean << " (16-texel truth 1.5, sparse taps 3.0), depth "
                  << meanDepth << " (truth 12.5, sparse 20.0)" << std::endl;
        need(std::abs(mean - 1.5f) < 2e-3f, "colour-track statistics are the true 16-texel box mean");
        need(std::abs(meanDepth - 12.5f) < 2e-3f, "colour-track statistics average all 16 depth texels");
        host.reset();
    }

    struct ChainFrame
    {
        // Uniform frames: the smoothed fields equal the inputs, so the expected gain is analytic.
        float colour[3] {};
        float input[3] {};
        float motionUv[2] {};
        float motionDepthDelta = 0.0f;
        float depth = 10.0f;
    };

    struct ChainResult
    {
        std::vector<uint8_t> composite;
        float share = 0.0f, lumaRatio = 0.0f, luma = 0.0f;
        // Frame mean level ratio: fp16 storage rounds each pixel's luma to ~2^-11, but the mean over the frame
        // cancels that rounding, so the level claim is measured at the mean and the pixel rounding is reported.
        float meanLevel = 0.0f;
    };

    ChainResult runChainFrame(Host& host, const Pipelines& pipelines, const Constants& constants, Scene& scene,
                              ID3D12Resource* colour, ID3D12Resource* input, ID3D12Resource* motion,
                              ID3D12Resource* depth, ID3D12Resource* normals, ID3D12Resource* stats,
                              ID3D12Resource* target, ID3D12Resource* motionOut, ID3D12Resource* gain,
                              ID3D12Resource* historyRead, ID3D12Resource* historyWrite, uint32_t w, uint32_t h,
                              const ChainFrame& frame, float emaWeight, float strength, bool historyValid)
    {
        std::vector<uint8_t> colourData(size_t(w) * h * 8), inputData(size_t(w) * h * 8);
        std::vector<uint8_t> motionData(size_t(w) * h * 8, 0);
        std::vector<float> depthData(size_t(w) * h);
        std::vector<uint32_t> normalData(size_t(w) * h);
        for (uint32_t y = 0; y < h; ++y)
            for (uint32_t x = 0; x < w; ++x)
            {
                const size_t pixel = size_t(y) * w + x;
                for (int channel = 0; channel < 3; ++channel)
                {
                    putHalf(colourData, pixel, channel, frame.colour[channel]);
                    putHalf(inputData, pixel, channel, frame.input[channel]);
                }
                putHalf(colourData, pixel, 3, 1.0f);
                putHalf(inputData, pixel, 3, 1.0f);
                putHalf(motionData, pixel, 0, frame.motionUv[0]);
                putHalf(motionData, pixel, 1, frame.motionUv[1]);
                putHalf(motionData, pixel, 2, frame.motionDepthDelta);
                putHalf(motionData, pixel, 3, 1.0f);
                depthData[pixel] = frame.depth;
                normalData[pixel] = (512u << 0) | (512u << 10) | (0u << 20) | (0u << 30);
            }
        uploadTexture(host, scene, colour, colourData.data(), colourData.size(), kRead);
        uploadTexture(host, scene, input, inputData.data(), inputData.size(), kRead);
        uploadTexture(host, scene, motion, motionData.data(), motionData.size(), kRead);
        uploadTexture(host, scene, depth, depthData.data(), depthData.size() * sizeof(float), kRead);
        uploadTexture(host, scene, normals, normalData.data(), normalData.size() * sizeof(uint32_t), kRead);

        std::vector<Descriptors> heaps;
        recordChain(host, pipelines, constants, heaps, colour, input, motion, depth, normals, stats, target,
                    motionOut, gain, historyRead, historyWrite, w, h, emaWeight, strength,
                    ColourTrackMath::kDefaultTapStep, historyValid);
        Readback read(host, colour, kRead);
        host.submit();
        host.checkDebug();
        auto data = read.bytes();   // the readback map must happen after the copy has executed

        ChainResult result;
        result.composite = data;
        const size_t centre = size_t(h / 2) * w + w / 2;
        const float outR = halfAt(data, centre, 0), outG = halfAt(data, centre, 1), outB = halfAt(data, centre, 2);
        result.share = outR / std::max(outR + outG + outB, 1e-6f);
        result.luma = luminance(outR, outG, outB);
        result.lumaRatio = result.luma / std::max(luminance(frame.colour[0], frame.colour[1], frame.colour[2]), 1e-9f);
        // The reference level is the STORED input level (the frame is uploaded as fp16), so the ratio measures the
        // pass and the output's own fp16 rounding, not a float-vs-half artifact of the test constants.
        const auto stored = [](float value) {
            return DirectX::PackedVector::XMConvertHalfToFloat(DirectX::PackedVector::XMConvertFloatToHalf(value));
        };
        double outSum = 0.0, inSum = 0.0;
        for (size_t pixel = 0; pixel < size_t(w) * h; ++pixel)
        {
            outSum += luminance(halfAt(data, pixel, 0), halfAt(data, pixel, 1), halfAt(data, pixel, 2));
            inSum += luminance(stored(frame.colour[0]), stored(frame.colour[1]), stored(frame.colour[2]));
        }
        result.meanLevel = float(outSum / std::max(inSum, 1e-9));
        host.reset();
        return result;
    }

    float shareOfRgb(const float rgb[3])
    {
        return rgb[0] / std::max(rgb[0] + rgb[1] + rgb[2], 1e-6f);
    }

    // ---- B) the chain moves chroma, keeps luminance; C) the EMA; D) the gates -----------------------------
    void chainChecks(Host& host, const Pipelines& pipelines, const Constants& constants)
    {
        constexpr uint32_t w = 64, h = 64;
        Scene scene(host, 8, 8);
        auto colour = makeTexture(host.device.Get(), w, h, kColour, L"ct colour");
        auto input = makeTexture(host.device.Get(), w, h, kColour, L"ct input");
        auto motion = makeTexture(host.device.Get(), w, h, kColour, L"ct motion");
        auto depth = makeTexture(host.device.Get(), w, h, kDepth, L"ct depth");
        auto normals = makeTexture(host.device.Get(), w, h, kNormals, L"ct normals");
        auto stats = makeTexture(host.device.Get(), w / 4, h / 4, kColour, L"ct stats");
        auto target = makeTexture(host.device.Get(), w / 4, h / 4, kColour, L"ct target");
        auto motionOut = makeTexture(host.device.Get(), w / 4, h / 4, kColour, L"ct motion out");
        auto gain = makeTexture(host.device.Get(), w / 4, h / 4, kColour, L"ct gain");
        ComPtr<ID3D12Resource> history[2] {makeTexture(host.device.Get(), w / 4, h / 4, kColour, L"ct history 0"),
                                          makeTexture(host.device.Get(), w / 4, h / 4, kColour, L"ct history 1")};

        // The colours keep every gain inside the shipped 0.75..1.33 clamp, so the expected chroma is the target's
        // exactly: the composite's R share is .42, frame 1's input .40, frame 2's .36 (EMA target .39). A larger
        // step would be capped by the clamp (measured: a .50 -> .30 step lands at .375), which is the documented
        // behaviour of the clamp, not a tracking failure.
        const ChainFrame frame1 {.colour = {0.42f, 0.29f, 0.29f}, .input = {0.40f, 0.30f, 0.30f}};
        const auto first = runChainFrame(host, pipelines, constants, scene, colour.Get(), input.Get(), motion.Get(),
                                         depth.Get(), normals.Get(), stats.Get(), target.Get(), motionOut.Get(),
                                         gain.Get(), history[0].Get(), history[1].Get(), w, h, frame1, 0.25f, 1.0f,
                                         false);
        const float inputShare1 = shareOfRgb(frame1.input);
        const float colourShare1 = shareOfRgb(frame1.colour);
        std::cout << "colour-track frame 1: share " << first.share << " (composite " << colourShare1
                  << ", target " << inputShare1 << "), pixel luma ratio " << first.lumaRatio << ", frame level "
                  << first.meanLevel << std::endl;
        need(std::abs(first.share - inputShare1) < 5e-3f,
             "frame 1 without history takes the composite's chroma onto the tracked target");
        need(std::abs(first.lumaRatio - 1.0f) < 1e-3f, "frame 1 keeps the pixel's luminance (fp16 rounding only)");
        need(std::abs(first.meanLevel - 1.0f) < 5e-4f, "frame 1 keeps the frame level (fp16 storage bound)");

        // Strength 0 must return the composite byte-identically: the gain is exactly 1, so the luminance restore
        // multiplies by exactly 1.0 and the fp16 round trip is exact.
        const auto zeroStrength = runChainFrame(host, pipelines, constants, scene, colour.Get(), input.Get(),
                                                motion.Get(), depth.Get(), normals.Get(), stats.Get(), target.Get(),
                                                motionOut.Get(), gain.Get(), history[0].Get(), history[1].Get(), w, h,
                                                frame1, 0.25f, 0.0f, false);
        bool identical = true;
        for (size_t pixel = 0; pixel < size_t(w) * h; ++pixel)
            for (int channel = 0; channel < 4; ++channel)
            {
                const uint16_t a = uint16_t(zeroStrength.composite[pixel * 8 + channel * 2] |
                                             (zeroStrength.composite[pixel * 8 + channel * 2 + 1] << 8));
                const float expected = channel < 3 ? frame1.colour[channel] : 1.0f;
                if (a != DirectX::PackedVector::XMConvertFloatToHalf(expected)) identical = false;
            }
        need(identical, "strength 0 returns the composite byte-identically");
        std::cout << "colour-track strength 0 identical: ok" << std::endl;

        // Frame 2: the same composite, a new input colour (R share .20), zero motion, matching depth. The EMA
        // target is lerp(frame1 input, frame2 input, 0.25) and the output has to sit exactly there.
        const ChainFrame frame2 {.colour = {0.42f, 0.29f, 0.29f}, .input = {0.36f, 0.32f, 0.32f}};
        const auto second = runChainFrame(host, pipelines, constants, scene, colour.Get(), input.Get(), motion.Get(),
                                          depth.Get(), normals.Get(), stats.Get(), target.Get(), motionOut.Get(),
                                          gain.Get(), history[1].Get(), history[0].Get(), w, h, frame2, 0.25f, 1.0f,
                                          true);
        float expected[3] {};
        for (int channel = 0; channel < 3; ++channel)
            expected[channel] = 0.75f * frame1.input[channel] + 0.25f * frame2.input[channel];
        const float expectedShare = shareOfRgb(expected);
        std::cout << "colour-track frame 2 (EMA): share " << second.share << " (expected " << expectedShare
                  << ", previous " << inputShare1 << ", new " << shareOfRgb(frame2.input) << "), pixel luma ratio "
                  << second.lumaRatio << ", frame level " << second.meanLevel << std::endl;
        need(std::abs(second.share - expectedShare) < 5e-3f, "the EMA weight is what moves the tracked colour");
        need(second.share > shareOfRgb(frame2.input) - 5e-3f && second.share < inputShare1 + 5e-3f,
             "a colour step is followed over frames, not at once");
        need(std::abs(second.lumaRatio - 1.0f) < 1e-3f, "frame 2 keeps the pixel's luminance (fp16 rounding only)");
        need(std::abs(second.meanLevel - 1.0f) < 5e-4f, "frame 2 keeps the frame level (fp16 storage bound)");

        // D1) the depth gate: the history's depth is 10, this frame's is 12 (20 %, far outside the 2 % tolerance),
        // so the EMA must restart from the current input colour.
        const ChainFrame disocclusion {.colour = {0.42f, 0.29f, 0.29f}, .input = {0.36f, 0.32f, 0.32f},
                                       .depth = 12.0f};
        const auto rejected = runChainFrame(host, pipelines, constants, scene, colour.Get(), input.Get(),
                                            motion.Get(), depth.Get(), normals.Get(), stats.Get(), target.Get(),
                                            motionOut.Get(), gain.Get(), history[1].Get(), history[0].Get(), w, h,
                                            disocclusion, 0.25f, 1.0f, true);
        std::cout << "colour-track depth gate: share " << rejected.share << " (restart " << shareOfRgb(frame2.input)
                  << ", blended " << expectedShare << ")" << std::endl;
        need(std::abs(rejected.share - shareOfRgb(frame2.input)) < 5e-3f,
             "a history whose depth disagrees beyond the tolerance is rejected");

        // D2) the off-screen warp: a 2 UV displacement leaves the frame, so the history is invalid even where
        // clamp addressing would return a plausible edge texel.
        const ChainFrame offscreen {.colour = {0.42f, 0.29f, 0.29f}, .input = {0.36f, 0.32f, 0.32f},
                                    .motionUv = {2.0f, 0.0f}};
        const auto warped = runChainFrame(host, pipelines, constants, scene, colour.Get(), input.Get(), motion.Get(),
                                          depth.Get(), normals.Get(), stats.Get(), target.Get(), motionOut.Get(),
                                          gain.Get(), history[1].Get(), history[0].Get(), w, h, offscreen, 0.25f, 1.0f,
                                          true);
        std::cout << "colour-track off-screen warp: share " << warped.share << std::endl;
        need(std::abs(warped.share - shareOfRgb(frame2.input)) < 5e-3f,
             "a warp that leaves the frame restarts from the current input colour");
    }

    // ---- A) OFF identity against the base composition CSO, and the target write ---------------------------
    void compositionChecks(Host& host, const Pipelines& pipelines)
    {
        constexpr uint32_t w = 64, h = 48;
        Scene scene(host, 8, 8);
        const auto texture = [&](const wchar_t* name, DXGI_FORMAT format) {
            return makeTexture(host.device.Get(), w, h, format, name);
        };
        auto specular = texture(L"comp spec", kColour);
        auto specAlbedo = texture(L"comp spec albedo", kAlbedo);
        auto diffuse = texture(L"comp diff", kColour);
        auto diffAlbedo = texture(L"comp diff albedo", kAlbedo);
        auto skip = texture(L"comp skip", kColour);
        auto normals = texture(L"comp normals", kNormals);
        auto depth = texture(L"comp depth", kDepth);
        auto motion = texture(L"comp motion", kColour);
        auto directSpecDenoised = texture(L"comp direct spec denoised", kColour);
        auto directSpecSignal = texture(L"comp direct spec signal", kColour);
        auto trust = texture(L"comp trust", DXGI_FORMAT_R32G32_FLOAT);
        auto indirectDiffDenoised = texture(L"comp indirect diff denoised", kColour);
        auto indirectSpecSignal = texture(L"comp indirect spec signal", kColour);
        auto directDiffSignal = texture(L"comp direct diff signal", kColour);
        auto colour = texture(L"comp colour", kColour);
        auto target = texture(L"comp target", kColour);

        const auto fillColour = [&](ID3D12Resource* resource, float r, float g, float b, float a) {
            std::vector<uint8_t> data(size_t(w) * h * 8);
            for (size_t pixel = 0; pixel < size_t(w) * h; ++pixel)
            {
                putHalf(data, pixel, 0, r); putHalf(data, pixel, 1, g);
                putHalf(data, pixel, 2, b); putHalf(data, pixel, 3, a);
            }
            uploadTexture(host, scene, resource, data.data(), data.size(), kRead);
        };
        const auto fillAlbedo = [&](ID3D12Resource* resource, uint8_t value) {
            std::vector<uint8_t> data(size_t(w) * h * 4, value);
            for (size_t pixel = 0; pixel < size_t(w) * h; ++pixel) data[pixel * 4 + 3] = 255;
            uploadTexture(host, scene, resource, data.data(), data.size(), kRead);
        };
        fillColour(specular.Get(), 0.3f, 0.2f, 0.1f, 1.0f);
        fillColour(diffuse.Get(), 0.2f, 0.3f, 0.4f, 1.0f);
        fillColour(skip.Get(), 0.0f, 0.0f, 0.0f, 1.0f);
        fillColour(motion.Get(), 0.0f, 0.0f, 0.0f, 1.0f);
        fillColour(directSpecDenoised.Get(), 0.0f, 0.0f, 0.0f, 1.0f);
        fillColour(directSpecSignal.Get(), 0.0f, 0.0f, 0.0f, 1.0f);
        fillColour(indirectDiffDenoised.Get(), 0.0f, 0.0f, 0.0f, 1.0f);
        fillColour(indirectSpecSignal.Get(), 0.6f, 0.4f, 0.2f, 1.0f);
        fillColour(directDiffSignal.Get(), 0.8f, 0.4f, 0.1f, 1.0f);
        fillAlbedo(specAlbedo.Get(), 128);  // 0.502
        fillAlbedo(diffAlbedo.Get(), 64);   // 0.251
        {
            std::vector<float> data(size_t(w) * h, 10.0f);
            uploadTexture(host, scene, depth.Get(), data.data(), data.size() * sizeof(float), kRead);
        }
        {
            std::vector<uint32_t> data(size_t(w) * h, (512u << 0) | (512u << 10));
            uploadTexture(host, scene, normals.Get(), data.data(), data.size() * sizeof(uint32_t), kRead);
        }
        {
            std::vector<float> data(size_t(w) * h * 2, 0.0f);
            uploadTexture(host, scene, trust.Get(), data.data(), data.size() * sizeof(float), kRead);
        }
        // A canary the shader must not touch while the colour-track flag is off.
        std::vector<uint8_t> canary(size_t(w) * h * 8);
        for (size_t i = 0; i < canary.size(); ++i) canary[i] = uint8_t(0x5a + (i % 7));
        const auto canaryBytes = canary;
        uploadTexture(host, scene, target.Get(), canary.data(), canary.size(), kRead);
        uploadTexture(host, scene, colour.Get(), canary.data(), canary.size(), kRead);

        const CompositionConstants constants {
            .DstTexSize = {float(w), float(h), 1.0f / float(w), 1.0f / float(h)},
            .Flags = 0u,
            .SourceUvScale = {1.0f, 1.0f},
            .SourceUvOffset = {},
            .SpecularAlbedoDemodulation = 1.0f,
            .DiffuseAlbedoModulation = 1.0f,
            .UnsupportedAlbedoRecovery = 0.0f,
            .DemodDivisorFloor = 8e-3f};
        auto upload = buffer(host.device.Get(), 256, D3D12_HEAP_TYPE_UPLOAD);
        uint8_t* mapped; hr(upload->Map(0, nullptr, reinterpret_cast<void**>(&mapped)));

        const Binding srvs[] {{specular.Get(), kColour}, {specAlbedo.Get(), kAlbedo}, {diffuse.Get(), kColour},
                              {diffAlbedo.Get(), kAlbedo}, {skip.Get(), kColour}, {normals.Get(), kNormals},
                              {depth.Get(), kDepth}, {motion.Get(), kColour}, {directSpecDenoised.Get(), kColour},
                              {directSpecSignal.Get(), kColour}, {trust.Get(), DXGI_FORMAT_R32G32_FLOAT},
                              {indirectDiffDenoised.Get(), kColour}, {indirectSpecSignal.Get(), kColour},
                              {directDiffSignal.Get(), kColour}};
        const auto runComposition = [&](ID3D12PipelineState* pso, ID3D12RootSignature* root, uint32_t flags,
                                        ID3D12Resource* targetUav) -> Descriptors {
            std::memcpy(mapped, &constants, sizeof(constants));
            *reinterpret_cast<uint32_t*>(mapped + 16) = flags;
            Descriptors descriptors(host, 16);
            barrier(host.list.Get(), colour.Get(), kRead, kWrite);
            if (targetUav) barrier(host.list.Get(), targetUav, kRead, kWrite);
            const Binding uavs[] {{colour.Get(), kColour}, {targetUav, kColour}};
            recordPass(host, descriptors, pso, root, upload.Get(), srvs, uavs, w, h);
            barrier(host.list.Get(), colour.Get(), kWrite, kRead);
            if (targetUav) barrier(host.list.Get(), targetUav, kWrite, kRead);
            return descriptors;   // the heap must outlive the submission
        };

        // 1) the base composition CSO, flag off, with the target descriptor left unbound (the base root signature
        //    has one UAV). Its output is the reference the shipped shader has to reproduce.
        auto baseHeap = runComposition(pipelines.basePso.Get(), pipelines.baseRoot.Get(), 0u, nullptr);
        Readback baseRead(host, colour.Get(), kRead);
        host.submit();
        host.checkDebug();
        auto base = baseRead.bytes();
        host.reset();

        // 2) the production composition CSO, flag off, target bound (and left untouched).
        auto offHeap = runComposition(pipelines.compPso.Get(), pipelines.compRoot.Get(), 0u, target.Get());
        Readback offRead(host, colour.Get(), kRead);
        Readback offTarget(host, target.Get(), kRead);
        host.submit();
        host.checkDebug();
        auto off = offRead.bytes();
        auto offTargetBytes = offTarget.bytes();
        host.reset();
        need(off == base, "the production composition with the colour-track flag off is byte-identical to the base");
        need(offTargetBytes == canaryBytes, "the colour-track target texture is untouched while the flag is off");
        std::cout << "colour-track OFF identity: composition " << off.size() << " bytes identical, target canary intact"
                  << std::endl;

        // 3) the production composition CSO with the flag on: the composite must stay byte-identical (the target
        //    write is an addition, not a change) and the target has to be RR's input colour in output units:
        //    InIndirectSpecularSignal * SpecularMultiplier + InDirectDiffuseSignal * DiffuseMultiplier.
        auto onHeap = runComposition(pipelines.compPso.Get(), pipelines.compRoot.Get(), 1u << 10, target.Get());
        Readback onRead(host, colour.Get(), kRead);
        Readback onTarget(host, target.Get(), kRead);
        host.submit();
        host.checkDebug();
        auto on = onRead.bytes();
        auto onTargetBytes = onTarget.bytes();
        host.reset();
        (void) baseHeap; (void) offHeap; (void) onHeap;
        need(on == base, "writing the colour-track target does not change the composite");
        const float expectedR = 0.6f * (128.0f / 255.0f) + 0.8f * (64.0f / 255.0f);
        const float expectedG = 0.4f * (128.0f / 255.0f) + 0.4f * (64.0f / 255.0f);
        const float expectedB = 0.2f * (128.0f / 255.0f) + 0.1f * (64.0f / 255.0f);
        const float gotR = halfAt(onTargetBytes, 0, 0), gotG = halfAt(onTargetBytes, 0, 1),
                    gotB = halfAt(onTargetBytes, 0, 2);
        std::cout << "colour-track target: (" << gotR << ", " << gotG << ", " << gotB << ") expected ("
                  << expectedR << ", " << expectedG << ", " << expectedB << ")" << std::endl;
        need(std::abs(gotR - expectedR) < 2e-3f && std::abs(gotG - expectedG) < 2e-3f &&
             std::abs(gotB - expectedB) < 2e-3f,
             "the target holds RR's input colour in output units");
    }

    // ---- E) the cost of the three dispatches ---------------------------------------------------------------
    void costChecks(Host& host, const Pipelines& pipelines)
    {
        std::vector<std::pair<uint32_t, uint32_t>> sizes {{1505u, 847u}};
        if (const char* knob = std::getenv("FSRD25_CT_RES"))
        {
            const std::string value(knob);
            const auto split = value.find('x');
            need(split != std::string::npos, "cost resolution knob is WxH");
            sizes = {{uint32_t(std::atoi(value.substr(0, split).c_str())),
                      uint32_t(std::atoi(value.substr(split + 1).c_str()))}};
        }
        else
            sizes.push_back({2560u, 1440u});
        for (const auto& [w, h] : sizes)
        {
            Scene scene(host, 8, 8);
            auto colour = makeTexture(host.device.Get(), w, h, kColour, L"ct cost colour");
            auto input = makeTexture(host.device.Get(), w, h, kColour, L"ct cost input");
            auto motion = makeTexture(host.device.Get(), w, h, kColour, L"ct cost motion");
            auto depth = makeTexture(host.device.Get(), w, h, kDepth, L"ct cost depth");
            auto normals = makeTexture(host.device.Get(), w, h, kNormals, L"ct cost normals");
            const uint32_t quarterW = std::max(1u, w / 4), quarterH = std::max(1u, h / 4);
            auto stats = makeTexture(host.device.Get(), quarterW, quarterH, kColour, L"ct cost stats");
            auto target = makeTexture(host.device.Get(), quarterW, quarterH, kColour, L"ct cost target");
            auto motionOut = makeTexture(host.device.Get(), quarterW, quarterH, kColour, L"ct cost motion out");
            auto gain = makeTexture(host.device.Get(), quarterW, quarterH, kColour, L"ct cost gain");
            ComPtr<ID3D12Resource> history[2] {makeTexture(host.device.Get(), quarterW, quarterH, kColour, L"ct cost history 0"),
                                               makeTexture(host.device.Get(), quarterW, quarterH, kColour, L"ct cost history 1")};
            {
                std::vector<uint8_t> colourData(size_t(w) * h * 8), inputData(size_t(w) * h * 8);
                std::vector<uint8_t> motionData(size_t(w) * h * 8, 0);
                std::vector<float> depthData(size_t(w) * h, 10.0f);
                std::vector<uint32_t> normalData(size_t(w) * h, (512u << 0) | (512u << 10));
                for (size_t pixel = 0; pixel < size_t(w) * h; ++pixel)
                {
                    putHalf(colourData, pixel, 0, 0.5f); putHalf(colourData, pixel, 1, 0.25f);
                    putHalf(colourData, pixel, 2, 0.25f); putHalf(colourData, pixel, 3, 1.0f);
                    putHalf(inputData, pixel, 0, 0.3f); putHalf(inputData, pixel, 1, 0.35f);
                    putHalf(inputData, pixel, 2, 0.35f); putHalf(inputData, pixel, 3, 1.0f);
                    putHalf(motionData, pixel, 3, 1.0f);
                }
                uploadTexture(host, scene, colour.Get(), colourData.data(), colourData.size(), kRead);
                uploadTexture(host, scene, input.Get(), inputData.data(), inputData.size(), kRead);
                uploadTexture(host, scene, motion.Get(), motionData.data(), motionData.size(), kRead);
                uploadTexture(host, scene, depth.Get(), depthData.data(), depthData.size() * sizeof(float), kRead);
                uploadTexture(host, scene, normals.Get(), normalData.data(), normalData.size() * sizeof(uint32_t), kRead);
            }
            Constants constants(host);
            std::vector<double> withTrack, withoutTrack;
            std::vector<Descriptors> heaps;   // one heap per recorded frame, alive until the submission completes
            for (uint32_t batch = 0; batch < 40; ++batch)
            {
                const bool tracked = (batch % 2u) == 0u;
                heaps.clear();
                for (uint32_t repetition = 0; repetition < 8; ++repetition)
                {
                    if (tracked)
                        recordChain(host, pipelines, constants, heaps, colour.Get(), input.Get(), motion.Get(),
                                    depth.Get(), normals.Get(), stats.Get(), target.Get(), motionOut.Get(), gain.Get(),
                                    history[0].Get(), history[1].Get(), w, h, 0.25f, 1.0f,
                                    ColourTrackMath::kDefaultTapStep, true);
                }
                const auto start = std::chrono::steady_clock::now();
                host.submit();
                const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start)
                                      .count() / 8.0;
                (tracked ? withTrack : withoutTrack).push_back(ms);
                host.reset();
            }
            std::sort(withTrack.begin(), withTrack.end());
            std::sort(withoutTrack.begin(), withoutTrack.end());
            const double median = withTrack[withTrack.size() / 2], baseline = withoutTrack[withoutTrack.size() / 2];
            std::cout << "colour-track cost at " << w << "x" << h << ": median " << median << " ms, p10 "
                      << withTrack[withTrack.size() / 10] << " ms, p90 " << withTrack[withTrack.size() * 9 / 10]
                      << " ms per frame (stats + track + apply); the same frame without them " << baseline
                      << " ms, so the passes cost " << (median - baseline) << " ms" << std::endl;
            const uint64_t bytes = uint64_t(w) * h * 8 + uint64_t(quarterW) * quarterH * 8 * 6;
            std::cout << "colour-track memory at " << w << "x" << h << ": " << bytes << " bytes ("
                      << (double(bytes) / (1024.0 * 1024.0)) << " MiB) in 7 textures" << std::endl;
        }
    }
}

int main(int argc, char** argv) try
{
    std::cout.setf(std::ios::unitbuf);
    need(argc == 2, "job JSON required");
    Host host;
    Pipelines pipelines(host);
    Constants constants(host);
    statsChecks(host, pipelines, constants);
    chainChecks(host, pipelines, constants);
    compositionChecks(host, pipelines);
    costChecks(host, pipelines);
    host.checkDebug();
    std::cout << "PASS checks=" << checks << " debug_errors=0 debug_warnings=0\n";
    return 0;
}
catch (const std::exception& error)
{
    std::cerr << error.what() << '\n';
    return 1;
}
