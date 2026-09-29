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
            const auto folder=Util::DllPath().parent_path()/"RRTrace"/
                ("additive_"+std::to_string(GetCurrentProcessId())+"_"+std::to_string(GetTickCount64()));
            if (!std::filesystem::create_directories(folder))
                throw std::runtime_error("capture output already exists");
            std::ostringstream metadata;
            metadata.imbue(std::locale::classic());
            metadata << std::setprecision(9);
            metadata << "{\"schema\":\"fsrd-additive-live-v1\",\"channels\":[\"R\",\"G\",\"B\"],"
                     << "\"origin\":["<<c.x<<','<<c.y<<"],\"size\":["<<c.width<<','<<c.height<<"],"
                     << "\"render_size\":["<<c.constants.DstTexSize.x<<','<<c.constants.DstTexSize.y<<"],"
                     << "\"configured_strength\":"<<c.constants.AdditiveLightSplit<<','
                     << "\"conversion_flags\":"<<c.constants.Flags<<','
                     << "\"trace_conversion_flags\":"<<(c.constants.Flags&0xffffu)<<','
                     << "\"specular_modulation\":"<<c.constants.SpecularAlbedoDemodulation<<','
                     << "\"diffuse_modulation\":"<<c.constants.DiffuseAlbedoModulation<<','
                     << "\"demod_divisor_floor\":"<<c.constants.DemodDivisorFloor<<','
                     << "\"comparison\":\"Same diagnostic experimental DXIL and source frame at strength 0/1; FP32 journal, not an AMD output A/B\","
                     << "\"shader_sha256\":\""<<RRTraceAdditiveIO::Sha256(RRTraceAdditive_cso)<<"\","
                     << "\"production_shader_sha256\":\""<<RRTraceAdditiveIO::Sha256(FSRDInputConvAdditive_cso)<<"\","
                     << "\"constants_sha256\":\""<<RRTraceAdditiveIO::HashObject(c.constants)<<"\",\"images\":[";
            RRTraceAdditiveIO::WriteFile(folder/"conversion_constants.bin",
                {reinterpret_cast<const uint8_t*>(&c.constants),sizeof(c.constants)});
            std::vector<uint8_t> bytes(size_t(c.width)*c.height*16);
            for (UINT i=0;i<96;++i)
            {
                void* mapped=nullptr;
                const SIZE_T extent=c.footprint.Offset+SIZE_T(c.footprint.Footprint.RowPitch)*c.height;
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
            metadata<<"]}";
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
            c->x=request[0]/8*8; c->y=request[1]/8*8;
            const UINT rw=UINT(original.DstTexSize.x), rh=UINT(original.DstTexSize.y);
            if (c->x>=rw || c->y>=rh) throw std::runtime_error("ROI outside render extent");
            c->width=std::min(request[2],rw-c->x); c->height=std::min(request[2],rh-c->y);
            c->shader.Initialize(m_pDev,GetAsByteSpan(RRTraceAdditive_cso),sizeof(original),17,8,
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
            c->ticket=RRTraceFence::Arm(m_pDev,cmd);
            for (auto& image:c->scratch) c->ticket->Retain(image.Get());
            for (auto& readback:c->readbacks) c->ticket->Retain(readback.Get());
            for (auto* input:inputs) if (input) c->ticket->Retain(input);
            c->ticket->Retain(c->shader.m_rootSig.Get());
            c->ticket->Retain(c->shader.m_pso.Get());
            c->ticket->Retain(c->shader.m_constUploadBuffer.Get());
            for (auto& heap:c->shader.m_frameHeaps) c->ticket->Retain(heap.GetHeapCSU());
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
