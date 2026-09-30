"""Fresh native raw-resource ablation of specular-albedo diagnostic alpha only."""
from pathlib import Path
import hashlib, itertools, json, re, shlex, shutil, subprocess
import numpy as np
from native_resource_guard import run_guarded

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
DEST=HERE/'evidence'
EXE=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_soft_temporal_long_alpha_fresh/fsrd_rr_runner.exe')
DLL=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
CASES={'material':ROOT/'tools_tmp/native_continuous_harmonic_fresh_retry_20260930/evidence/material',
       'wave':ROOT/'tools_tmp/native_continuous_harmonic_remaining_20260930/evidence/wave'}
VARIANTS=('original','zero','one','source_alpha')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def parse_job(p):
    rows=[shlex.split(row) for row in p.read_text().splitlines()]
    assert len(rows)==9 and list(map(int,rows[0][:8]))==[128,80,64,2,32,0,1,0]
    assert Path(rows[0][8])==DLL
    assert [int(row[1]) for row in rows[1:8]]==[41,10,24,28,28,10,10]
    return rows

def prepare():
    target=HERE/'pre_native_freeze.json'
    if target.exists():raise ValueError('Preserve registration')
    assert sha(EXE)=='3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2'
    assert sha(DLL)=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
    sources={str(p):sha(p) for p in (HERE/'analyze.py',HERE/'native_resource_guard.py',EXE,DLL)}
    for folder in CASES.values():
        parse_job(folder/'harmonic_pilot/job.txt')
        for name in ('harmonic_pilot','observed'):
            for p in (folder/name).iterdir():
                if p.is_file() and p.name in ['job.txt','frame_controls.txt','camera.txt','dispatch_controls.bin','amd_context_identity.json','diffuse.bin','specular.bin']+[f'input{i}.bin' for i in range(7)]:
                    sources[str(p)]=sha(p)
    registration=dict(schema='specular-albedo-diagnostic-alpha-raw-native-ablation-v1',
        cases=list(CASES),variants=list(VARIANTS),native_contexts=8,native_RR_calls=512,
        changed_resource='input3 RGBA8_UNORM specular-albedo alpha only; original RGB byte-identical',
        controls='All 184-byte applied frame records must match original; fresh independent context each variant',
        outputs='Raw FP16 diffuse and specular RGBA; exact bytes and RGB/alpha RMS/max/per-frame comparisons',
        diagnostic_only=True,quality_accepted=False,game_run=False,
        no_conversion_or_composition=True,no_truth=True,
        limits=['Two frozen synthetic harmonic-pilot inputs only, no universal SDK contract inference',
                'Fresh original versus previous original measures context variation; do not average or subtract it',
                'The older all_nonradiance_counterfactual_inputs_exact field checked guide RGB, not all guide RGBA bytes'],
        sources=sources)
    save(target,registration)
    print(json.dumps({'registered':str(target),'sha256':sha(target),'sources':len(sources)}),flush=True)

def alpha_full(folder):
    row=parse_job(folder/'job.txt')[4]
    count=int(row[2]);assert count in (1,64)
    arr=np.fromfile(row[0],np.uint8).reshape(count,80,128,4)
    return np.broadcast_to(arr,(64,80,128,4))[...,3]

def compare(a,b):
    aa=np.fromfile(a,'<f2').reshape(64,80,128,4)
    bb=np.fromfile(b,'<f2').reshape(64,80,128,4)
    result={'bytes_exact':a.read_bytes()==b.read_bytes(),'all_finite':bool(np.isfinite(aa).all() and np.isfinite(bb).all())}
    for channels,label in [(slice(0,3),'RGB'),(slice(3,4),'alpha'),(slice(None),'RGBA')]:
        delta=aa[...,channels].astype('f8')-bb[...,channels].astype('f8')
        result[label]={'rms':float(np.sqrt(np.mean(delta**2))),'max_abs':float(np.max(abs(delta))),
            'changed_fraction':float(np.mean(delta!=0)),'per_frame_rms':np.sqrt(np.mean(delta**2,axis=(1,2,3))).tolist()}
    return result

def main():
    if DEST.exists():raise ValueError('Preserve existing evidence')
    freeze=json.loads((HERE/'pre_native_freeze.json').read_text())
    assert all(sha(p)==digest for p,digest in freeze['sources'].items())
    DEST.mkdir();snap=DEST/'source_snapshot';snap.mkdir()
    for p in HERE.iterdir():
        if p.is_file():shutil.copyfile(p,snap/p.name)
    report=dict(schema=freeze['schema'],status='running',completed_native_contexts=0,native_RR_calls=0,
                quality_accepted=False,game_run=False,pre_native_freeze_sha256=sha(HERE/'pre_native_freeze.json'),rows=[])
    def checkpoint():save(DEST/'results.json',report)
    checkpoint()
    try:
      for case,source in CASES.items():
        original=source/'harmonic_pilot';rows=parse_job(original/'job.txt');case_dir=DEST/case;case_dir.mkdir()
        original_rgba=np.fromfile(original/'input3.bin',np.uint8).reshape(int(rows[4][2]),80,128,4)
        assert original_rgba.shape[0]==64
        source_a=alpha_full(source/'observed')
        row_report={'case':case,'source_alpha_difference_fraction':float(np.mean(source_a!=original_rgba[...,3])),
                    'contexts':{},'comparisons':{}}
        report['rows'].append(row_report);checkpoint()
        for variant in VARIANTS:
            folder=case_dir/variant;folder.mkdir();newrows=[]
            for i,row in enumerate(rows[1:8]):
                target=folder/f'input{i}.bin';shutil.copyfile(Path(row[0]),target)
                if i==3 and variant!='original':
                    arr=original_rgba.copy()
                    arr[...,3]=0 if variant=='zero' else 255 if variant=='one' else source_a
                    assert np.array_equal(arr[...,:3],original_rgba[...,:3])
                    arr.tofile(target)
                if i!=3 or variant=='original':assert sha(target)==sha(Path(row[0]))
                newrows.append(f'"{target.as_posix()}" {row[1]} {row[2]}')
            for name in ('frame_controls.txt','camera.txt'):
                if (original/name).exists():shutil.copyfile(original/name,folder/name)
            od=folder/'diffuse.bin';os=folder/'specular.bin';job=folder/'job.txt'
            job.write_text('\n'.join([' '.join(rows[0][:8])+f' "{DLL.as_posix()}"']+newrows+[f'"{od.as_posix()}" "{os.as_posix()}"'])+'\n')
            input_identity={f'input{i}.bin':sha(folder/f'input{i}.bin') for i in range(7)}
            save(folder/'amd_input_identity.json',input_identity)
            guard=run_guarded([str(EXE),str(job)],folder)
            if guard['status']!='completed':raise RuntimeError('Guard/native failure: '+str(folder))
            report['completed_native_contexts']+=1;report['native_RR_calls']+=64;checkpoint()
            log=(folder/'stdout.log').read_text(errors='replace')+(folder/'stderr.log').read_text(errors='replace')
            (folder/'runner.log').write_text(log)
            for field in ('validation_errors','validation_warnings','sdk_errors','sdk_warnings'):
                assert re.search(r'\b'+field+r'=0\b',log),log
            assert 'debug_layer=1' in log
            assert all(p.stat().st_size==64*80*128*8 for p in (od,os))
            assert sha(folder/'dispatch_controls.bin')==sha(original/'dispatch_controls.bin')
            identity=dict(inputs=input_identity,runner_sha256=sha(EXE),dll_sha256=sha(DLL),
                applied_dispatch_sha256=sha(folder/'dispatch_controls.bin'),outputs={p.name:sha(p) for p in (od,os)},
                only_changed_resource='specular-albedo input3 alpha',validated_zero_errors_warnings=True)
            save(folder/'amd_context_identity.json',identity)
            row_report['contexts'][variant]=identity;checkpoint()
            print(case,variant,'completed',flush=True)
        for left,right in itertools.combinations(VARIANTS,2):
            row_report['comparisons'][left+'__'+right]={name:compare(case_dir/left/name,case_dir/right/name) for name in ('diffuse.bin','specular.bin')}
        row_report['fresh_original_vs_previous']={name:compare(case_dir/'original'/name,original/name) for name in ('diffuse.bin','specular.bin')}
        checkpoint()
      assert report['completed_native_contexts']==8
      assert all(sha(p)==digest for p,digest in freeze['sources'].items())
      report['all_ablation_pairs_raw_outputs_exact']=all(v['bytes_exact'] for row in report['rows'] for pair in row['comparisons'].values() for v in pair.values())
      report['status']='completed_native_diagnostic_not_solution';checkpoint()
      print(json.dumps({'contexts':8,'RR_calls':512,'all_pairs_raw_exact':report['all_ablation_pairs_raw_outputs_exact']}),flush=True)
    except BaseException as exc:
      report.update(status='failed_preserved',error=type(exc).__name__+': '+str(exc));checkpoint();raise

if __name__=='__main__':
    import sys
    prepare() if '--prepare' in sys.argv else main()
