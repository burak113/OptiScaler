struct ComputeState
{
    ID3D12Device* m_pDev = nullptr;
    
    ComPtr<ID3D12RootSignature> m_rootSig;
    ComPtr<ID3D12PipelineState> m_pso;
    std::vector<FrameDescriptorHeap> m_frameHeaps;

    ComPtr<ID3D12Resource> m_constUploadBuffer;
    byte* m_cbMappedData = nullptr;
    UINT m_cbSlotSize = 0;
    UINT m_cbCurrentFrameIndex = 0;
    UINT backBufferCount = kBackBufferCount;

    ~ComputeState()
    {
        if (m_constUploadBuffer && m_cbMappedData)
        {
            m_constUploadBuffer->Unmap(0, nullptr);
            m_cbMappedData = nullptr;
        }
    }

    void Initialize(
        ID3D12Device* pDev,
        std::span<const byte> bytecode,
        UINT cbDataSize,
        UINT numSrvs,
        UINT numUavs,
        LPCWSTR cbName,
        UINT backBufferCount = kBackBufferCount)
    {
        m_pDev = pDev;
        this->backBufferCount = backBufferCount;

        // Create Root Signature
        ThrowIfFailed(m_pDev->CreateRootSignature(0, bytecode.data(), bytecode.size(), IID_PPV_ARGS(&m_rootSig)),
              "Failed to create Root Signature");

        // Create PSO
        D3D12_COMPUTE_PIPELINE_STATE_DESC psoDesc = {};
        psoDesc.pRootSignature = m_rootSig.Get();
        psoDesc.CS = { bytecode.data(), bytecode.size() };
        ThrowIfFailed(m_pDev->CreateComputePipelineState(&psoDesc, IID_PPV_ARGS(&m_pso)), "Failed to create PSO");

        // Create Constant Buffer Upload Heap
        m_cbSlotSize = AlignTo256(cbDataSize);
        const UINT bufferSize = m_cbSlotSize * backBufferCount;

        D3D12_HEAP_PROPERTIES heapProps = { D3D12_HEAP_TYPE_UPLOAD };
        D3D12_RESOURCE_DESC bufferDesc = {};
        bufferDesc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        bufferDesc.Width = bufferSize;
        bufferDesc.Height = 1;
        bufferDesc.DepthOrArraySize = 1;
        bufferDesc.MipLevels = 1;
        bufferDesc.SampleDesc.Count = 1;
        bufferDesc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        bufferDesc.Flags = D3D12_RESOURCE_FLAG_NONE;

        ThrowIfFailed(m_pDev->CreateCommittedResource(&heapProps, D3D12_HEAP_FLAG_NONE, &bufferDesc, 
        D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&m_constUploadBuffer)), "Failed to create Constant Buffer");
        
        m_constUploadBuffer->SetName(cbName);
        D3D12_RANGE readRange = { 0, 0 }; 
        ThrowIfFailed(m_constUploadBuffer->Map(0, &readRange, reinterpret_cast<void**>(&m_cbMappedData)), "Failed to map Constant Buffer");

        m_frameHeaps.resize(backBufferCount);

        // Create Descriptor Heaps
        for (auto& heap : m_frameHeaps)
        {
            if (!heap.Initialize(m_pDev, numSrvs, numUavs, 0, 0))
                throw std::runtime_error("Failed to initialize FrameDescriptorHeap");
        }
    }

    void Dispatch(
        ID3D12GraphicsCommandList* cmdList,
        std::span<const byte> cbData,
        std::span<ID3D12Resource* const> inputs,
        std::span<const MipChainDesc> inputMips,
        std::span<ID3D12Resource*> output,
        std::span<const UINT> outputMips,
        XMFLOAT2 outDim,
        bool autoBarrierOutput = true,
        ID3D12PipelineState* pipelineState = nullptr
    )
    {
        if (!cmdList) 
            return;

        ScopedSkipHeapCapture skipHeapCapture {};

        // Constant Buffer Updates
        const UINT currentFrame = m_cbCurrentFrameIndex;
        const UINT currentOffset = currentFrame * m_cbSlotSize;
        memcpy(m_cbMappedData + currentOffset, cbData.data(), cbData.size());

        D3D12_GPU_VIRTUAL_ADDRESS cbAddress = m_constUploadBuffer->GetGPUVirtualAddress() + currentOffset;
        m_cbCurrentFrameIndex = (m_cbCurrentFrameIndex + 1) % backBufferCount;

        // Transitions SRV -> UAV
        if (autoBarrierOutput)
            AddBarriers(cmdList, output, outputMips, kSrvState, kUavState);

        // Update descriptors
        FrameDescriptorHeap& currentHeap = m_frameHeaps[currentFrame];
        CreateSRVs(m_pDev, currentHeap, inputs, inputMips);
        CreateUAVs(m_pDev, currentHeap, output, outputMips);

        // Configure pipeline
        cmdList->SetPipelineState(pipelineState ? pipelineState : m_pso.Get());
        cmdList->SetComputeRootSignature(m_rootSig.Get());

        ID3D12DescriptorHeap* heaps[] = { currentHeap.GetHeapCSU() };
        cmdList->SetDescriptorHeaps(1, heaps);
        cmdList->SetComputeRootConstantBufferView(0, cbAddress);

        // SRV table
        cmdList->SetComputeRootDescriptorTable(1, currentHeap.GetTableGPUStart());

        // UAV table
        CD3DX12_GPU_DESCRIPTOR_HANDLE uavTable = currentHeap.GetTableGPUStart();
        uavTable.Offset((UINT)inputs.size(), m_pDev->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV));
        cmdList->SetComputeRootDescriptorTable(2, uavTable);

        // Dispatch
        const UINT dimX = ((UINT)outDim.x + (kThreadGroupSizeX - 1)) / kThreadGroupSizeX;
        const UINT dimY = ((UINT)outDim.y + (kThreadGroupSizeY - 1)) / kThreadGroupSizeY;
        cmdList->Dispatch(dimX, dimY, 1);

        // Transition the UAVs back to SRV
        if (autoBarrierOutput)
            AddBarriers(cmdList, output, outputMips, kUavState, kSrvState);
    }

    void Dispatch(
        ID3D12GraphicsCommandList* cmdList,
        std::span<const byte> cbData,
        std::span<ID3D12Resource* const> inputs,
        std::span<ID3D12Resource*> output,
        XMFLOAT2 outDim,
        bool autoBarrierOutput = true,
        ID3D12PipelineState* pipelineState = nullptr
    )
    {
        Dispatch(cmdList, cbData, inputs, {}, output, {}, outDim, autoBarrierOutput, pipelineState);
    }
};
