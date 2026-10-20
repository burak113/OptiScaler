const CaptureJson controls {
                        {"jitter",CaptureJson::parse(RRTraceAdditiveIO::FloatArray(upscalerDesc.jitterOffset))},
                        {"motion_vector_scale",CaptureJson::parse(RRTraceAdditiveIO::FloatArray(upscalerDesc.motionVectorScale))},
                        {"render_size",{upscalerDesc.renderSize.width,upscalerDesc.renderSize.height}},
                        {"upscale_size",{upscalerDesc.upscaleSize.width,upscalerDesc.upscaleSize.height}},
                        {"frame_time_delta",upscalerDesc.frameTimeDelta},{"pre_exposure",upscalerDesc.preExposure},
                        {"reset",upscalerDesc.reset},{"flags",upscalerDesc.flags},{"create_flags",_upscaleCtxDesc.flags},
                        {"camera_near",upscalerDesc.cameraNear},{"camera_far",upscalerDesc.cameraFar},
                        {"camera_fov_vertical",upscalerDesc.cameraFovAngleVertical},
                        {"view_space_to_meters",upscalerDesc.viewSpaceToMetersFactor},
                        {"enable_sharpening",upscalerDesc.enableSharpening},{"sharpness",upscalerDesc.sharpness}
                    };
                    