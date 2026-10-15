"""Copy-only particle guides: production WARP recorder, default inertness and slots."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import test_fsrd_game_trace_capture as host
from fsrd_toolchain import compile_cpp

MAIN = r'''
int main(int argc,char** argv) try
{
    need(argc==2,"output directory required");
    g_dllPath=std::filesystem::path(argv[1])/"test_OptiScaler.dll";
    Host h; Json results=Json::object();
    for (unsigned mode=0;mode<3;++mode)
    {
        Trace capture; Trace::Request request;
        request.x=3; request.y=5; request.frameCount=128;
        request.particleLayerDiagnostics=mode!=0;
        need(Trace::RequestStart(request),"request rejected");
        need(Trace::WantsParticleLayerDiagnostics()==(mode!=0),"capture option not latched");
        const char* name=mode==0 ? "off" : (mode==1 ? "bound" : "unbound");
        results[name]=Trace::GetStatus().folder;
        h.Fill(0);
        std::vector<Trace::DiagnosticSource> inputs(h.diagnostics.begin(),h.diagnostics.end());
        for (unsigned guide=0;guide<2;++guide)
        {
            Trace::DiagnosticSource d;
            d.name=guide==0 ? "raw_color_before_particles" : "raw_color_before_transparency";
            d.active=mode!=2; d.required=false;
            d.image={mode==2 ? nullptr : h.textures[guide].Get(),srv};
            d.baseX=2; d.baseY=1;
            d.inactiveReason="Fixture title did not bind optional guide.";
            inputs.push_back(d);
        }
        const auto deadline=GetTickCount64()+15000;
        while (!capture.RecordSources(h.device.Get(),h.list.Get(),h.sources,h.renderWidth,h.renderHeight,
            h.constants,inputs,std::span<const uint8_t>(h.seed.data(),128),{},true))
        {
            const auto status=Trace::GetStatus();
            if (!status.active || status.phase=="error" || status.phase=="draining" || GetTickCount64()>=deadline)
                throw std::runtime_error("source admission failed: "+status.message);
            Sleep(1);
        }
        const std::array<Trace::DiagnosticSource,3> native {{
            {"rr_specular",{h.textures[0].Get(),srv}},
            {"rr_diffuse",{h.textures[1].Get(),srv}},
            {"flat_detail_reference",{h.textures[3].Get(),srv}}
        }};
        capture.RecordNative(h.list.Get(),{h.textures[0].Get(),srv},h.Frame(0),native);
        capture.CompleteFrame(h.list.Get(),{h.textures[0].Get(),srv});
        h.Execute(); Published(1); h.Reset(); capture.Poll();
        Trace::RequestStop(); Closed();
        need(Trace::GetStatus().captured==1,"particle capture did not publish exactly one frame");
        need(!Trace::WantsParticleLayerDiagnostics(),"stopped diagnostic remained active");
    }
    h.NoGpuErrors();
    RRTraceAdditiveIO::WriteText(std::filesystem::path(argv[1])/"particle-captures.json",results.dump(2));
    std::cout<<"Particle guide recorder WARP PASS\n";
    return 0;
}
catch (const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
'''


def run():
    started = time.perf_counter()
    output = Path(os.environ['FSRD_GPU_TEST_OUTPUT']).resolve()
    output.mkdir(parents=True, exist_ok=True)
    stubs = output / 'stubs'
    stubs.mkdir(exist_ok=True)
    (stubs / 'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n')
    (stubs / 'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\n'
                                 'namespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }\n')
    root = host.ROOT
    feature = (root / 'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp').read_text(encoding='utf-8-sig')
    start = feature.index('const auto array =', feature.index('if (FSRDGameTraceSession::IsActive())'))
    end = feature.index('// Fingerprint applied semantic controls only.', start)
    (stubs / 'fsrd_game_trace_controls.inc').write_text(feature[start:end], encoding='utf-8')
    start = feature.index('const CaptureJson controls {', feature.index('if (FSRDConvShader && FSRDGameTraceSession::WantsSrOutput())'))
    end = feature.index("// FSR's output is UAV here.", start)
    (stubs / 'fsrd_game_trace_sr_controls.inc').write_text(feature[start:end], encoding='utf-8')
    cpp = host.CPP[:host.CPP.index('int main(')] + MAIN
    cpp = cpp.replace('__RECORDER__', (root / 'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix())
    cpp = cpp.replace('__RR_HEADER__', (root / 'OptiScaler/include/fsr-rr/ffx_denoiser.h').as_posix())
    source = output / 'particle_diagnostics.cpp'
    source.write_text(cpp)
    exe = output / 'particle_diagnostics.exe'
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'bcrypt.lib'),
                (stubs, root / 'OptiScaler', root / 'external/streamline', root / 'external/nlohmann', root / 'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    subprocess.run([str(exe), str(output)], check=True)
    folders = json.loads((output / 'particle-captures.json').read_text())
    checks = 0

    def check(okay):
        nonlocal checks
        assert okay
        checks += 1

    for mode, folder in folders.items():
        folder = Path(folder)
        manifest = json.loads((folder / 'capture.json').read_text())
        check(manifest['manifest_published_frames'] == 1)
        frame = manifest['frames'][0]
        rows = {r['name']: r for r in frame['diagnostics']}
        check(rows['flat_detail_reference']['available'])
        check(rows['rr_specular']['available'] and rows['rr_diffuse']['available'])
        if mode == 'off':
            check('particle_layer_diagnostics' not in manifest)
            check('raw_color_before_particles' not in rows and 'raw_color_before_transparency' not in rows)
            check(len(rows) == 24)
        else:
            check(manifest['particle_layer_diagnostics']['particle_bypass'] is False)
            check(len(rows) == 26)
            for guide in ('raw_color_before_particles', 'raw_color_before_transparency'):
                row = rows[guide]
                check(row['available'] == (mode == 'bound'))
                check(row['bound'] == (mode == 'bound'))
                if mode == 'bound':
                    data = (folder / row['file']).read_bytes()
                    check(len(data) == 128 * 128 * 8)
                    check(hashlib.sha256(data).hexdigest() == row['sha256'])
                    # Request origin (3,5) plus title subrect base (2,1).
                    # Verify original half words, not only their stored hash.
                    import numpy as np
                    words = np.frombuffer(data, '<u2').reshape(128, 128, 4)
                    x = np.arange(128, dtype=np.uint16)[None, :, None]
                    y = np.arange(128, dtype=np.uint16)[:, None, None]
                    c = np.arange(4, dtype=np.uint16)[None, None, :]
                    expected = 0x3000 + 11 + x + y + c if guide == 'raw_color_before_particles' else np.zeros_like(words)
                    check(np.array_equal(words, expected))
                else:
                    check('file' not in row and 'Fixture title' in row['reason'])
    report = dict(status='PASS', checks=checks, seconds=time.perf_counter()-started,
                  scope='WARP original-word copy, unbound optional guides, OFF no guide rows/readbacks, native Flat/lobe slot separation')
    (output / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    run()
