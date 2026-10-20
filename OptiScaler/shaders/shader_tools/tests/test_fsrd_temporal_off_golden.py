"""Byte-for-byte OFF replay against baseadccf08fd, with identical deterministic provider lighting.
Actual GPU transforms, RR input words, dispatch controls and title commits are compared.
This is an equivalence test, not an RR quality experiment or a claim of deterministic ML inference.
The base side is the task base commit's whole fsrd_preprocess tree: replacing single files broke once the
bridge settings gained members that the recovery header reads (task 24 T1), so the base side is materialised
from the commit instead of being patched into the current tree.
"""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
sys.path[:0]=[str(HERE),str(HERE.parent),'E:/FSRD/rrlab']
from fsrd_toolchain import compile_cpp,dxc
from test_fsrd_nrd_bridge_rr import bounded_run
from rrlab.captures import Capture

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    out=Path(os.environ['FSRD_GPU_TEST_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
    frozen=out/'input';frozen.mkdir();c=Capture('f2ef375f')
    for target,source,dt,ch in [('spec','input_specular','f2',4),('diff','input_diffuse','f2',4),
        ('depth','input_depth','f4',1),('motion','input_motion','f2',4),('normals','input_normal_roughness','u4',1),
        ('spec_albedo','input_specular_albedo','u1',4),('diff_albedo','input_diffuse_albedo','u1',4)]:
        words=np.frombuffer(c.raw(20,source),dt).reshape(c.H,c.W,ch)
        words[150:278,304:432].tofile(frozen/(target+'.bin'))
    variants={};source_manifest={}
    for label in ['base','current']:
        overlay=out/label;work=overlay/'work';work.mkdir(parents=True)
        for rel in ['OptiScaler/shaders/fsrd_preprocess','OptiScaler/shaders/shader_tools/tests']:
            dst=overlay/rel;dst.mkdir(parents=True)
            src=ROOT/rel
            if rel.endswith('tests'):
                for n in ['nrd_bridge_rr_fixture.cpp','nrd_bridge_rr_test_support.h']:
                    shutil.copyfile(src/n,dst/n)
            else:
                for p in src.rglob('*'):
                    if p.is_file() and p.suffix in ('.h','.cpp','.cso','.hlsl'):
                        q=dst/p.relative_to(src);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
        # Same unmodified dependency headers, with relative includes preserved.
        for rel in ['OptiScaler/misc','OptiScaler/shaders']:
            dst=overlay/rel;dst.mkdir(parents=True,exist_ok=True)
            for p in (ROOT/rel).glob('*.h'):shutil.copyfile(p,dst/p.name)
        replaced={}
        if label=='base':
            commit=os.environ.get('FSRD_OFF_GOLDEN_BASE','adccf08fd')
            tree=subprocess.check_output(['git','-C',str(ROOT),'ls-tree','-r','--name-only',commit,
                'OptiScaler/shaders/fsrd_preprocess']).decode().split()
            for rel in tree+['OptiScaler/shaders/shader_tools/tests/nrd_bridge_rr_fixture.cpp']:
                data=subprocess.check_output(['git','-C',str(ROOT),'show',commit+':'+rel])
                (overlay/rel).write_bytes(data);replaced[rel]=hashlib.sha256(data).hexdigest()
            # The base tree has no task-24 additions: drop the overlay copies the commit does not know.
            preprocess=overlay/'OptiScaler/shaders/fsrd_preprocess'
            for p in sorted(preprocess.rglob('*'),reverse=True):
                if p.is_file() and p.relative_to(overlay).as_posix() not in tree:p.unlink()
        fixture=overlay/'OptiScaler/shaders/shader_tools/tests'
        support=fixture/'nrd_bridge_rr_test_support.h';text=support.read_text()
        text=text.replace('struct FfxApiProxy\n{','void GoldenSnapshot(const ffxDispatchDescDenoiser&,const ffxDispatchDescDenoiserDirectDiffuse&,const ffxDispatchDescDenoiserIndirectSpecular&);\nstruct FfxApiProxy\n{')
        assert text.count('        ++dispatches;')==1
        text=text.replace('        ++dispatches;','        GoldenSnapshot(lastDispatch,lastDiffuse,lastSpecular);\n        ++dispatches;')
        support.write_text(text)
        (work/'pch.h').write_text('#pragma once\n')
        shader=work/'consumer.cso'
        subprocess.run([str(dxc()),'-T','cs_6_2','-E','CSMain','-O3','-force-rootsig-ver','rootsig_1_0',str(HERE/'nrd_bridge_consumer_fixture.hlsl'),'-Fo',str(shader)],check=True)
        (work/'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {'+','.join(map(str,shader.read_bytes()))+'};\n')
        source=work/'golden.cpp'
        source.write_text((HERE/'fsrd_temporal_off_golden.cpp').read_text().replace(
            '#include "nrd_bridge_rr_fixture.cpp"','#include "'+(fixture/'nrd_bridge_rr_fixture.cpp').as_posix()+'"'))
        exe=work/'golden.exe';os.environ['FSRD_CPP_CACHE']=str(work/'cache')
        compile_cpp(source,exe,['d3d12.lib','dxgi.lib','d3dcompiler.lib'],
            [fixture,work,overlay/'OptiScaler',ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/streamline',ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api',HERE])
        result=overlay/'result'
        log,peak,seconds,path=bounded_run([str(exe),str(frozen),str(result)],work/'run')
        assert 'debug_errors=0 debug_warnings=0' in log and 'PASS temporal OFF golden' in log
        variants[label]=dict(seconds=seconds,peak_resident_bytes=peak,log=str(path))
        source_manifest[label]=dict(replaced=replaced,wrapper_sha256=sha(overlay/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp'),fixture_sha256=sha(fixture/'nrd_bridge_rr_fixture.cpp'))
    first=out/'base/result';second=out/'current/result';files=sorted(p.name for p in first.iterdir())
    assert files==sorted(p.name for p in second.iterdir())
    mismatches=[n for n in files if (first/n).read_bytes()!=(second/n).read_bytes()]
    result=dict(passed=not mismatches,base=os.environ.get('FSRD_OFF_GOLDEN_BASE','adccf08fd'),profiles=4,frames=24,files=len(files),
        compared_bytes=sum((first/n).stat().st_size for n in files),mismatches=mismatches,
        scope='actual D3D12 RR-wrapper transforms/dispatch inputs/controls/title commits and allocation+configure counts; deterministic provider RGB; frozen captured input crop; no quality or installed-game claim',
        cases=variants,source_manifest=source_manifest)
    (out/'result.json').write_text(json.dumps(result,indent=1));print(json.dumps(result,indent=1),flush=True)
    assert not mismatches,mismatches
    print('PASS OFF golden byte equivalence',flush=True)
if __name__=='__main__':main()
