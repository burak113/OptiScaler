const auto array = [](const auto& object) {
                        return CaptureJson::parse(RRTraceAdditiveIO::FloatArray(object));
                    };
                    CaptureJson controls {
                        {"view",array(denoiserDesc.view)}, {"projection",array(denoiserDesc.projection)},
                        {"jitter",array(denoiserDesc.jitterOffsets)},
                        {"camera_delta",array(denoiserDesc.cameraPositionDelta)},
                        {"motion_vector_scale",array(denoiserDesc.motionVectorScale)},
                        {"depth_bounds",array(denoiserDesc.linearDepthBounds)},
                        {"render_size",{denoiserDesc.renderSize.width,denoiserDesc.renderSize.height}},
                        {"pre_exposure",std::isfinite(capturePreExposure) ? CaptureJson(capturePreExposure) : CaptureJson(nullptr)},
                        {"pre_exposure_provided",capturePreExposureProvided},
                        {"motion_history_valid",_convDesc.MotionHistoryValid},
                        {"output_scope","actual_configured_composition_before_sr"}
                    };
                    