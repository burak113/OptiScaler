Json CopyFootprintMetadata(const Image& image)
{
    const auto& footprint = image.footprint.Footprint;
    return {{"offset",image.footprint.Offset},{"row_pitch",footprint.RowPitch},
        {"extent",{footprint.Width,footprint.Height,footprint.Depth}},
        {"dxgi_format",uint32_t(footprint.Format)},{"rows",footprint.Height},
        {"row_bytes",uint64_t(footprint.Width)*image.bpp},{"requested_buffer_bytes",image.footprintBytes},
        {"committed_buffer_bytes",image.allocationBytes},
        {"cpu_crop_origin_in_readback",{image.readbackCropX,image.readbackCropY}}};
}
