"""Run every nonempty radiance layout through the real AMD RR provider.

Checks dispatch acceptance, independent outputs and D3D12 validation. Synthetic scenes
are a wiring/ABI check, not an in-game image-quality acceptance test.
"""
from pathlib import Path
import hashlib,json,os,re,subprocess,sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

def run():
    root=Path(__file__).resolve().parents[4]
    out=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT',root/'tools_tmp/fsrd_menu_20261004/native'))
    out.mkdir(parents=True,exist_ok=True)
    dll=root/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
    assert dll.is_file(),dll
    runner=out/'fsrd_signal_layout_rr_test.exe'
    previous_cl=os.environ.get('CL')
    os.environ['CL']=(previous_cl or '')+f' /I"{root / "external/FidelityFX-SDK/ffx-api/include/ffx_api"}"'
    try:
        compile_cpp(Path(__file__).with_name('fsrd_signal_layout_rr_test.cpp'),runner,('d3d12.lib','dxgi.lib'))
    finally:
        if previous_cl is None: os.environ.pop('CL',None)
        else: os.environ['CL']=previous_cl
    w,h,frames=128,96,3
    def rgba(rgb,alpha=0):
        value=np.zeros((h,w,4),np.float32); value[...,:3]=rgb; value[...,3]=alpha; return value
    normal=np.full((h,w),1023|(1023<<10)|(205<<20),np.uint32)
    records=[]
    for mask in range(1,16):
        case=out/f'layout_{mask:04b}'; case.mkdir(exist_ok=True)
        df=(2 if mask&1 else 0)|(16 if mask&4 else 0)
        sf=(4 if mask&2 else 0)|(32 if mask&8 else 0)
        two_d=(mask&5)==5; two_s=(mask&10)==10
        inputs=[(np.full((h,w),10,np.float32),41),(rgba((0,0,0)),10),(normal,24),
                (rgba((.2,.2,.2)),28),(rgba((.5,.5,.5)),28),
                (rgba((.25,.35,.45),8)*(np.array([.5,.5,.5,1]) if two_d else 1),10),
                (rgba((.15,.2,.25),6)*(np.array([.5,.5,.5,1]) if two_s else 1),10)]
        lines=[f'{w} {h} {frames} {df} {sf} 0 1 0 "{dll.as_posix()}"']
        for i,(data,fmt) in enumerate(inputs):
            if fmt==10: data=data.astype('<f2')
            elif fmt==28: data=np.rint(np.clip(data,0,1)*255).astype('u1')
            path=case/f'input_{i}.bin'; data.tofile(path)
            lines.append(f'"{path.as_posix()}" {fmt} 1')
        paths=[case/'diffuse.bin',case/'specular.bin',case/'extra_diffuse.bin',case/'extra_specular.bin']
        lines.append(f'"{paths[0].as_posix()}" "{paths[1].as_posix()}"')
        job=case/'job.txt'; job.write_text('\n'.join(lines)+'\n')
        result=subprocess.run([str(runner),str(job)],capture_output=True,text=True,timeout=55)
        (case/'native.log').write_text(result.stdout+result.stderr)
        assert result.returncode==0,result.stdout+result.stderr
        assert 'debug_layer=1' in result.stdout
        counts={k:int(v) for k,v in re.findall(r'(validation_errors|validation_warnings|sdk_errors|sdk_warnings)=(\d+)',result.stdout)}
        assert len(counts)==4 and not any(counts.values()),(mask,counts,result.stderr)
        for active,path in zip([bool(df),bool(sf),two_d,two_s],paths):
            if not active: continue
            pixels=np.fromfile(path,dtype='<f2').reshape(frames,h,w,4)[...,:3]
            assert np.all(np.isfinite(pixels)) and np.any(pixels>0),path
        records.append(dict(mask=mask,signals=mask.bit_count(),frames=frames,**counts))
        print(f'PASS native RR layout {mask:04b} ({mask.bit_count()} signals)',flush=True)
    (out/'native_results.json').write_text(json.dumps({'dll':str(dll),'dll_sha256':hashlib.sha256(dll.read_bytes()).hexdigest(),'layouts':records},indent=2))
    print(f'{len(records)} native layouts, {len(records)*frames} AMD RR dispatches passed')

if __name__=='__main__': run()
