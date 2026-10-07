// Floor quality replay uses the existing native AMD RR implementation. That
// implementation uploads explicit textures, retains one RR context for the
// sequence and reads both outputs back after a GPU fence. Keeping it included
// also makes the shared compile cache fingerprint its implementation and SDK.
// This entry point excludes its depth-range passthrough control: a Floor replay
// must execute RR at the supplied scene depth, rather than return an RR bypass.
#define main fsrd_floor_native_dispatch_main
#include "fsrd_rr_runner.cpp"
#undef main

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
