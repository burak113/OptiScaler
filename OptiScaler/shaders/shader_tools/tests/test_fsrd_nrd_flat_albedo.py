"""Production native Flat Albedo Recovery GPU/wrapper checks and known RESET-prefix observations.

Run through lead_ops/run_task_test.py (shared GPU lock). Capture diagnostics use
the unmodified floor-code2 signed-provider observations from the water probe;
this is six known frames, never a 64-frame temporal-quality replay or clean truth.
"""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
import numpy as np
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
sys.path.insert(0,str(HERE.parent))
from fsrd_toolchain import compile_cpp,dxc

CAPTURE=Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE/c7294a8e-9d11-4533-9d1d-4c7e10925993')
PROBE=Path('F:/FSRD/sol_batch/15-nrd-ghosting/water-new-captures-20261016/provider-roughness-r1/floor_code2')
PROVIDER=Path('F:/SteamLibrary/steamapps/common/Cyberpunk 2077/bin/x64/amd_fidelityfx_denoiser_dx12.dll')
PIN='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,data):p.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def main():
    out=Path(os.environ['FSRD_GPU_TEST_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
    assert not (out/'job.json').exists(),'Fresh output directory required'
    manifest=json.loads((CAPTURE/'capture.json').read_text())
    assert len(manifest['frames'])==6 and manifest['frames'][0]['actual_reset']
    assert sha(PROVIDER)==PIN
    # Existing fixture's signed-load entry is pinned to the same exact binary.
    fixture_dll=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll')
    assert sha(fixture_dll)==PIN
    names={'spec':'input_specular','diff':'input_diffuse','depth':'input_depth','motion':'input_motion',
           'normals':'input_normal_roughness','spec_albedo':'input_specular_albedo','diff_albedo':'input_diffuse_albedo'}
    rows=[]
    for i,frame in enumerate(manifest['frames']):
        folder=out/f'frame-{i}';folder.mkdir()
        images={image['name']:image for image in frame['images']}
        for name,role in names.items():
            source=CAPTURE/images[role]['file'];(folder/f'{name}.bin').write_bytes(source.read_bytes())
        for lobe in ('specular','diffuse'):
            source=PROBE/f'{i}-{lobe}-x256.bin'
            signal=np.fromfile(source,'<f2').reshape(847,1505,4).astype('f4');signal[...,:3]/=256
            signal.astype('<f2').tofile(folder/f'rr_{lobe}.bin')
        rows.append(dict(inputs=str(folder),output=str(folder/'recovered'),sdk_frame=frame['sdk_frame_index'],reset=frame['actual_reset']))
    save(out/'job.json',dict(width=1505,height=847,frames=rows))
    (out/'pch.h').write_text('#pragma once\n')
    shader=out/'consumer.cso'
    subprocess.run([str(dxc()),'-T','cs_6_2','-E','CSMain','-O3','-force-rootsig-ver','rootsig_1_0',str(HERE/'nrd_bridge_consumer_fixture.hlsl'),'-Fo',str(shader)],check=True)
    (out/'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {'+','.join(str(x) for x in shader.read_bytes())+'};\n')
    exe=out/'flat-native.exe'
    compile_cpp(HERE/'fsrd_nrd_flat_albedo.cpp',exe,['d3d12.lib','dxgi.lib','d3dcompiler.lib'],
        [out,ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/nlohmann',ROOT/'external/streamline',ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
    start=time.perf_counter()
    run=subprocess.run([str(exe),str(out/'job.json')],capture_output=True,text=True,timeout=180,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (out/'stdout.log').write_text(run.stdout);(out/'stderr.log').write_text(run.stderr)
    print(run.stdout,flush=True)
    if run.returncode:print(run.stderr,flush=True)
    run.check_returncode()
    assert 'flat_capture_frames=6 debug_errors=0 debug_warnings=0' in run.stdout
    measurements=[]
    for i,frame in enumerate(manifest['frames']):
        folder=out/f'frame-{i}'
        nr=np.fromfile(folder/'normals.bin','<u4').reshape(847,1505);rough=(nr>>20)&1023
        for lobe,name in (('specular','spec'),('diffuse','diff')):
            raw=np.fromfile(folder/f'rr_{lobe}.bin','<f2').reshape(847,1505,4)
            result=np.fromfile(folder/'recovered'/f'{lobe}.bin','<f2').reshape(847,1505,4)
            noisy=np.fromfile(folder/f'{name}.bin','<f2').reshape(847,1505,4)
            active=(rough<2)&np.isfinite(noisy[...,3])&(noisy[...,3]>=0)
            assert np.isfinite(result).all()
            assert np.array_equal(raw.view('u2')[...,3],result.view('u2')[...,3])
            assert np.array_equal(raw.view('u2')[~active],result.view('u2')[~active])
            measurements.append(dict(frame=i,lobe=lobe,active_pixels=int(active.sum()),
                changed_pixels=int(np.any(raw[...,:3]!=result[...,:3],-1).sum()),
                alpha_bit_exact=True,off_mask_bit_exact=True,
                rms_correction=float(np.sqrt(np.mean((raw[active,:3].astype('f4')-result[active,:3].astype('f4'))**2)))))
    save(out/'result.json',dict(passed=True,seconds=time.perf_counter()-start,exe_sha256=sha(exe),provider_sha256=PIN,
        capture_sha256=sha(CAPTURE/'capture.json'),measurements=measurements,
        scope='actual production wrapper mock+signed provider branches; actual existing flat shaders on six known full captured frames with floor2 provider observations; no native NRD output/history; no clean quality truth or long temporal claim'))
    print(json.dumps(dict(passed=True,output=str(out),measurements=measurements)),flush=True)
if __name__=='__main__':main()
