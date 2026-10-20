struct NativeObservationState
{
    FSRDNrdObservation::Stamp stamp;
    uint64_t recordingId = 0;
    uint32_t frameSL = UINT32_MAX, width = 0, height = 0;
    uint32_t cropX = 0, cropY = 0, cropWidth = 0, cropHeight = 0;
    bool actualReset = false, adopted = false;
    // Original S/D, then after-anchor/pre-turn S/D. Only equal resources at
    // this SAME observation time share an image. Never alias across stages.
    std::array<size_t,4> physicalRoles {};
    std::array<ID3D12Resource*,4> physicalSources {};
    std::array<FSRDNrdObservation::Surface,2> raw, selected;
    std::array<FSRDNrdObservation::SelectionWitness,2> selection;
};
