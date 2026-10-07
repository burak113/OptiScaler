// Floor quality replay uses the existing native AMD RR implementation. That
// implementation uploads explicit textures, retains one RR context for the
// sequence and reads both outputs back after a GPU fence. Keeping it included
// also makes the shared compile cache fingerprint its implementation and SDK.
// This entry point excludes its depth-range passthrough control: a Floor replay
// must execute RR at the supplied scene depth, rather than return an RR bypass.
#include <array>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

// An optional, versioned file beside the job supplies all moving-camera controls.
// The shared runner's existing camera.txt/frame_controls.txt contract is retained.
// Parse the complete file before the first dispatch so truncated captures, extra
// records and nonfinite matrices cannot silently become partial temporal replays.
template<class Dispatch>
void floorReplayFrameCamera(Dispatch& dispatch, unsigned frame, unsigned frames, const char* job)
{
    static const auto records = [&]() {
        std::vector<std::array<float, 40>> result;
        const auto path = std::filesystem::path(job).parent_path() / "frame_camera.txt";
        std::ifstream input(path);
        if (!input)
        {
            if (std::filesystem::exists(path))
                throw std::runtime_error("per-frame camera file open failed");
            return result;
        }
        std::string version;
        unsigned count;
        input >> version >> count;
        if (!input || version != "fsrd_frame_camera_v1" || count != frames)
            throw std::runtime_error("invalid per-frame camera header/count");
        result.resize(count);
        for (unsigned index = 0; index < count; ++index)
        {
            unsigned ordinal;
            input >> ordinal;
            if (!input || ordinal != index)
                throw std::runtime_error("per-frame camera ordinal must be contiguous");
            for (float& value : result[index])
            {
                input >> value;
                if (!input || !std::isfinite(value))
                    throw std::runtime_error("invalid/nonfinite per-frame camera value");
            }
            if (!(result[index][38] < result[index][39]))
                throw std::runtime_error("per-frame camera depth bounds must ascend");
        }
        input >> std::ws;
        if (!input.eof())
            throw std::runtime_error("trailing per-frame camera records");
        std::cout << "custom_frame_camera=1 frame_camera_records=" << count << '\n';
        return result;
    }();
    if (records.empty())
        return;
    const auto& values = records.at(frame);
    dispatch.motionVectorScale = {values[0], values[1], values[2]};
    dispatch.cameraPositionDelta = {values[3], values[4], values[5]};
    std::memcpy(&dispatch.view, values.data() + 6, 16 * sizeof(float));
    std::memcpy(&dispatch.projection, values.data() + 22, 16 * sizeof(float));
    dispatch.linearDepthBounds = {values[38], values[39]};
}

#define FSRD_RR_FRAME_CAMERA_HOOK floorReplayFrameCamera
#define FSRD_RR_EXTRA_SIGNALS 1
#define main fsrd_floor_native_dispatch_main
#include "fsrd_rr_runner.cpp"
#undef main
#undef FSRD_RR_FRAME_CAMERA_HOOK
#undef FSRD_RR_EXTRA_SIGNALS

int main(int argc, char** argv)
{
    try
    {
        if (argc != 2)
            throw std::runtime_error("usage: fsrd_floor_rr_replay job.txt");
        std::ifstream job(argv[1]);
        unsigned width, height, frames, diffuse, specular, resetEvery, tuning, passthrough;
        std::string dll;
        job >> width >> height >> frames >> diffuse >> specular >> resetEvery >> tuning >> passthrough
            >> std::quoted(dll);
        if (!job || !width || !height || !frames || passthrough || resetEvery > 1 || tuning > 1 ||
            (diffuse != 0 && diffuse != FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE &&
             diffuse != FFX_DENOISER_SIGNAL_INDIRECT_DIFFUSE) ||
            (specular != 0 && specular != FFX_DENOISER_SIGNAL_DIRECT_SPECULAR &&
             specular != FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR) || !(diffuse | specular))
            throw std::runtime_error("invalid native RR replay header (passthrough is prohibited)");
        std::cout << "harness=actual_amd_rr_floor_replay context_lifetime=sequence passthrough=0\n";
        return fsrd_floor_native_dispatch_main(argc, argv);
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
