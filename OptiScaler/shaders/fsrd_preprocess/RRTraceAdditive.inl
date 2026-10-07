// Included inside Impl. All resources are capture-owned until queue completion
// AND command-list Reset. No frame-count heuristic is used for readback safety.
    struct AdditiveCapture
    {
        ComputeState shader;
        std::array<ComPtr<ID3D12Resource>,8> scratch;
        std::array<ComPtr<ID3D12Resource>,96> readbacks;
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint {};
        std::shared_ptr<RRTraceFence::Ticket> ticket;
        Conversion::Constants constants {};
        ComPtr<ID3D12Resource> outputReadback;
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT outputFootprint {};
        ID3D12GraphicsCommandList* recordingList=nullptr; // Identity held by ticket.
        std::string pairedMetadata;
        bool outputRecorded=false;
        UINT x=0, y=0, width=0, height=0;
        bool started=false;
        ~AdditiveCapture()
        {
            if (ticket)
            {
                if (!started) ticket->CancelUnrecorded();
                ticket->Abandon();
                RRTraceFence::Forget(ticket);
            }
        }
    };
    std::unique_ptr<AdditiveCapture> m_additiveCapture;

    void PollAdditiveCapture() noexcept
    {
        if (!m_additiveCapture) return;
        try
        {
            auto& c=*m_additiveCapture;
            if (c.ticket->Invalid()) throw std::runtime_error("capture submission/reset was invalidated");
            if (!c.ticket->Ready()) return;
            if (!c.outputRecorded) throw std::runtime_error("No matching successful normal RR composition");
            const auto folder=Util::DllPath().parent_path()/"RRTrace"/
                ("additive_"+std::to_string(GetCurrentProcessId())+"_"+std::to_string(GetTickCount64()));
            if (!std::filesystem::create_directories(folder))
                throw std::runtime_error("capture output already exists");
            std::ostringstream metadata;
            metadata.imbue(std::locale::classic());
            metadata << std::setprecision(9);
            metadata << "{\"schema\":\"fsrd-additive-live-v2\",\"channels\":[\"R\",\"G\",\"B\"],"
                     << "\"origin\":["<<c.x<<','<<c.y<<"],\"size\":["<<c.width<<','<<c.height<<"],"
                     << "\"render_size\":["<<c.constants.DstTexSize.x<<','<<c.constants.DstTexSize.y<<"],"
                     << "\"configured_strength\":"<<c.constants.AdditiveLightSplit<<','
                     << "\"conversion_flags\":"<<c.constants.Flags<<','
                     << "\"trace_conversion_flags\":"<<(c.constants.Flags&0xffffu)<<','
                     << "\"specular_modulation\":"<<c.constants.SpecularAlbedoDemodulation<<','
                     << "\"diffuse_modulation\":"<<c.constants.DiffuseAlbedoModulation<<','
                     << "\"demod_divisor_floor\":"<<c.constants.DemodDivisorFloor<<','
                     << "\"paired\":"<<c.pairedMetadata<<','
                     << "\"comparison\":\"Same diagnostic DXIL/source at strength 0/1, plus actual configured pre-SR composition; not an AMD output A/B\","
                     << "\"shader_sha256\":\""<<RRTraceAdditiveIO::Sha256(RRTraceAdditive_cso)<<"\","
                     << "\"production_shader_sha256\":\""<<RRTraceAdditiveIO::Sha256(
                         c.constants.AdditiveLightSplit>0 ? std::span<const uint8_t>(FSRDInputConvAdditive_cso)
                                                          : std::span<const uint8_t>(FSRDInputConv_cso))<<"\","
                     << "\"constants_sha256\":\""<<RRTraceAdditiveIO::HashObject(c.constants)<<"\",\"images\":[";
            RRTraceAdditiveIO::WriteFile(folder/"conversion_constants.bin",
                {reinterpret_cast<const uint8_t*>(&c.constants),sizeof(c.constants)});
            std::vector<uint8_t> bytes(size_t(c.width)*c.height*16);
            for (UINT i=0;i<96;++i)
            {
                void* mapped=nullptr;
                const SIZE_T extent=c.footprint.Offset+SIZE_T(c.footprint.Footprint.RowPitch)*(c.height-1)+SIZE_T(c.width)*16;
                D3D12_RANGE read {0,extent};
                ThrowIfFailed(c.readbacks[i]->Map(0,&read,&mapped),"additive readback map failed");
                for (UINT y=0;y<c.height;++y)
                    memcpy(bytes.data()+size_t(y)*c.width*16,
                        static_cast<uint8_t*>(mapped)+c.footprint.Offset+size_t(y)*c.footprint.Footprint.RowPitch,
                        size_t(c.width)*16);
                D3D12_RANGE written {0,0}; c.readbacks[i]->Unmap(0,&written);
                const std::string name="strength"+std::to_string(i/48)+"_"+kAdditiveFieldNames[i%48];
                RRTraceAdditiveIO::WriteFile(folder/(name+".f32"),bytes);
                if (i) metadata<<',';
                metadata<<"{\"name\":"<<RRTraceAdditiveIO::Quote(name)<<",\"file\":"
                        <<RRTraceAdditiveIO::Quote(name+".f32")<<",\"format\":\"RGBA32_FLOAT\",\"sha256\":\""
                        <<RRTraceAdditiveIO::Sha256(bytes)<<"\"}";
            }
            bytes.resize(size_t(c.width)*c.height*8);
            void* mapped=nullptr;
            D3D12_RANGE read {0,c.outputFootprint.Offset+SIZE_T(c.outputFootprint.Footprint.RowPitch)*(c.height-1)+SIZE_T(c.width)*8};
            ThrowIfFailed(c.outputReadback->Map(0,&read,&mapped),"paired output map failed");
            for (UINT y=0;y<c.height;++y)
                memcpy(bytes.data()+size_t(y)*c.width*8,
                    static_cast<uint8_t*>(mapped)+c.outputFootprint.Offset+size_t(y)*c.outputFootprint.Footprint.RowPitch,
                    size_t(c.width)*8);
            D3D12_RANGE written {0,0}; c.outputReadback->Unmap(0,&written);
            RRTraceAdditiveIO::WriteFile(folder/"pre_sr_output.f16",bytes);
            metadata<<",{\"name\":\"pre_sr_output\",\"file\":\"pre_sr_output.f16\","
                    <<"\"format\":\"RGBA16_FLOAT\",\"sha256\":\""<<RRTraceAdditiveIO::Sha256(bytes)<<"\"}]}";
            RRTraceAdditiveIO::WriteText(folder/"capture.json",metadata.str());
            m_additiveCapture.reset();
            std::scoped_lock lock(g_additiveTraceMutex);
            g_additiveTraceBusy=false;
            const auto utf8=folder.u8string();
            g_additiveTraceStatus="Saved additive RRTrace: "+std::string(utf8.begin(),utf8.end());
        }
        catch (const std::exception& e)
        {
            m_additiveCapture.reset();
            std::scoped_lock lock(g_additiveTraceMutex);
            g_additiveTraceBusy=false;
            g_additiveTraceStatus=std::string("Additive capture rejected: ")+e.what();
        }
    }

    void CaptureAdditive(ID3D12GraphicsCommandList* cmd, const Conversion::Constants& original,
                         std::span<ID3D12Resource* const> inputs) noexcept
    {
        // A new conversion ends the opportunity to pair the preceding evaluation.
        // Never combine its input with a later frame, even on the same command list.
        if (m_additiveCapture && !m_additiveCapture->outputRecorded)
            m_additiveCapture->ticket->Invalidate();
        PollAdditiveCapture();
        if (m_additiveCapture) return;
        std::array<UINT,3> request {};
        {
            std::scoped_lock lock(g_additiveTraceMutex);
            if (!g_additiveTraceRequest || g_additiveTraceBusy) return;
            request=*g_additiveTraceRequest;
            g_additiveTraceRequest.reset();
            g_additiveTraceBusy=true;
            g_additiveTraceStatus="Recording additive channels; waiting for queue completion and Reset.";
        }
        try
        {
            ScopedSkipHeapCapture skipHeapCapture {};
            if (!ResTrack_Dx12::EnsureRRTraceHooks(m_pDev))
                throw std::runtime_error("queue/Reset hooks unavailable");
            auto c=std::make_unique<AdditiveCapture>();
            c->constants=original;
            c->recordingList=cmd;
            if (original.Flags & uint32_t(ConvFlags::Debug))
                throw std::runtime_error("Paired capture requires a normal rendering frame");
            c->x=request[0]/8*8; c->y=request[1]/8*8;
            const UINT rw=UINT(original.DstTexSize.x), rh=UINT(original.DstTexSize.y);
            if (c->x>=rw || c->y>=rh) throw std::runtime_error("ROI outside render extent");
            c->width=std::min(request[2],rw-c->x); c->height=std::min(request[2],rh-c->y);
            c->shader.Initialize(m_pDev,GetAsByteSpan(RRTraceAdditive_cso),sizeof(original),Conversion::Input::kCount,8,
                                 L"RRTrace_Additive_CB",12);
            for (auto& image:c->scratch)
                image=CreateTexture2D(m_pDev,c->width,c->height,DXGI_FORMAT_R32G32B32A32_FLOAT,
                                      L"RRTrace_Additive",kSrvState);
            UINT64 size=0;
            const auto desc=c->scratch[0]->GetDesc();
            m_pDev->GetCopyableFootprints(&desc,0,1,0,&c->footprint,nullptr,nullptr,&size);
            D3D12_HEAP_PROPERTIES heap {D3D12_HEAP_TYPE_READBACK};
            auto buffer=CD3DX12_RESOURCE_DESC::Buffer(size);
            for (auto& readback:c->readbacks)
                ThrowIfFailed(m_pDev->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&buffer,
                    D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&readback)),"additive readback allocation failed");
            auto outputDesc=desc; outputDesc.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
            m_pDev->GetCopyableFootprints(&outputDesc,0,1,0,&c->outputFootprint,nullptr,nullptr,&size);
            auto outputBuffer=CD3DX12_RESOURCE_DESC::Buffer(size);
            ThrowIfFailed(m_pDev->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&outputBuffer,
                D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&c->outputReadback)),"paired readback allocation failed");
            c->ticket=RRTraceFence::Arm(m_pDev,cmd);
            for (auto& image:c->scratch) c->ticket->Retain(image.Get());
            for (auto& readback:c->readbacks) c->ticket->Retain(readback.Get());
            c->ticket->Retain(c->outputReadback.Get());
            for (auto* input:inputs) if (input) c->ticket->Retain(input);
            c->ticket->Retain(c->shader.m_rootSig.Get());
            c->ticket->Retain(c->shader.m_pso.Get());
            // Every Dispatch below registers its exact shared DispatchLease, including
            // its immutable CB/heap slot, before writing or recording commands. The
            // generic recording/submission registry retains it independently of this
            // capture/ticket through Reset and every queue completion. Raw COM holds
            // of pool slots would not prevent shared-slot reuse and are not sufficient.
            m_additiveCapture=std::move(c);
            auto& capture=*m_additiveCapture;
            auto constants=original;
            constants.Flags &= 0xffffu; // Capture normal conversion, not menu debug-color replacement.
            constants.InspectorScale=float(capture.x); constants.DebugDepthMax=float(capture.y);
            std::array<ID3D12Resource*,8> outputs {};
            for (UINT i=0;i<8;++i) outputs[i]=capture.scratch[i].Get();
            capture.started=true;
            for (UINT strength=0;strength<2;++strength)
                for (UINT page=0;page<6;++page)
                {
                    constants.AdditiveLightSplit=float(strength);
                    constants.InspectorChannel=page;
                    // ComputeState::Dispatch is void and throws on unavailable tracking;
                    // failure enters the capture catch before any readback copy below.
                    capture.shader.Dispatch(cmd,{reinterpret_cast<const byte*>(&constants),sizeof(constants)},
                        inputs,outputs,{float(capture.width),float(capture.height)});
                    for (UINT slot=0;slot<8;++slot)
                    {
                        D3D12_RESOURCE_BARRIER barrier=CD3DX12_RESOURCE_BARRIER::Transition(outputs[slot],kSrvState,D3D12_RESOURCE_STATE_COPY_SOURCE);
                        cmd->ResourceBarrier(1,&barrier);
                        D3D12_TEXTURE_COPY_LOCATION src {},dst {};
                        src.pResource=outputs[slot]; src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
                        dst.pResource=capture.readbacks[strength*48+page*8+slot].Get();
                        dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint=capture.footprint;
                        cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
                        std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter);
                        cmd->ResourceBarrier(1,&barrier);
                    }
                }
            capture.ticket->Recorded();
        }
        catch (const std::exception& e)
        {
            if (m_additiveCapture && m_additiveCapture->ticket) m_additiveCapture->ticket->Invalidate();
            m_additiveCapture.reset();
            std::scoped_lock lock(g_additiveTraceMutex);
            g_additiveTraceBusy=false;
            g_additiveTraceStatus=std::string("Additive capture unavailable: ")+e.what();
        }
    }

    void CompleteAdditiveCapture(ID3D12GraphicsCommandList* cmd,
        const ffxDispatchDescDenoiser& dispatch, const CompositionDesc& composition,
        float preExposure, bool provided) noexcept
    {
        if (!m_additiveCapture || m_additiveCapture->outputRecorded) return;
        auto& c=*m_additiveCapture;
        try
        {
            if (cmd!=c.recordingList || c.ticket->Invalid() ||
                (composition.Flags & uint32_t(CompFlags::Debug)) ||
                dispatch.renderSize.width!=UINT(c.constants.DstTexSize.x) ||
                dispatch.renderSize.height!=UINT(c.constants.DstTexSize.y) ||
                !std::isfinite(preExposure) || preExposure<=0)
                throw std::runtime_error("Mismatched or invalid paired RR evaluation");
            auto* output=m_compositionOutput.Get();
            const auto desc=output->GetDesc();
            if (desc.Format!=DXGI_FORMAT_R16G16B16A16_FLOAT ||
                c.x+c.width>desc.Width || c.y+c.height>desc.Height)
                throw std::runtime_error("Invalid paired output extent/format");
            std::ostringstream m;
            m.imbue(std::locale::classic()); m<<std::setprecision(9);
            m<<"{\"frame_index\":"<<dispatch.frameIndex<<",\"dispatch_flags\":"<<dispatch.flags
             <<",\"reset\":"<<((dispatch.flags&FFX_DENOISER_DISPATCH_RESET)?"true":"false")
             <<",\"pre_exposure\":"<<preExposure<<",\"pre_exposure_provided\":"<<(provided?"true":"false")
             <<",\"exposure_scope\":\"NGX/SR metadata; RR has no pre-exposure dispatch field\""
             <<",\"output_scope\":\"Actual configured composed color before SR, including Floor/detail recovery\""
             <<",\"view\":"<<RRTraceAdditiveIO::FloatArray(dispatch.view)
             <<",\"projection\":"<<RRTraceAdditiveIO::FloatArray(dispatch.projection)
             <<",\"jitter\":"<<RRTraceAdditiveIO::FloatArray(dispatch.jitterOffsets)
             <<",\"motion_scale\":"<<RRTraceAdditiveIO::FloatArray(dispatch.motionVectorScale)
             <<",\"camera_delta\":"<<RRTraceAdditiveIO::FloatArray(dispatch.cameraPositionDelta)
             <<",\"linear_depth_bounds\":"<<RRTraceAdditiveIO::FloatArray(dispatch.linearDepthBounds)
             <<",\"composition_flags\":"<<composition.Flags
             <<",\"recovery_mask\":"<<composition.RecoveryMask
             <<",\"spatial_temporal_mask\":"<<composition.SpatialTemporalMask
             <<",\"composition_controls\":"<<RRTraceAdditiveIO::FloatArray(std::array<float,7>{
                 composition.FloorDetailPreservation,composition.FloorHandoverAnchorClamp,
                 composition.FloorHandoverCorrelationMix,composition.SpecularAlbedoDemodulation,
                 composition.DiffuseAlbedoModulation,composition.LumaRecovery,composition.ChromaRecovery})<<'}';
            c.pairedMetadata=m.str();
            c.ticket->Retain(output);
            RRTraceAdditiveIO::CopyPreSrRoi(cmd,output,c.outputReadback.Get(),c.outputFootprint,
                c.x,c.y,c.width,c.height);
            c.outputRecorded=true;
        }
        catch (...) { c.ticket->Invalidate(); }
    }
