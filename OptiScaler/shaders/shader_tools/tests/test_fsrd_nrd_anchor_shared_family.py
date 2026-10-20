"""Exact coordinator policy + real native anchor sharing of one Service budget."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=Path(os.environ.get('FSRD_NATIVE_ANCHOR_TEST_ROOT',str(HERE.parents[3]))).resolve()
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests'
sys.path.insert(0,str(TESTS))
import test_fsrd_native_post_motion_anchor as native


def sha(data):return hashlib.sha256(data).hexdigest()


def source_gates(source):
    text=source.decode('utf-8').replace('\r\n','\n');markers=('if (succeeded &&','if (prepared &&')
    result=[]
    for marker in markers:
        found=[];start=0
        while True:
            start=text.find(marker,start)
            if start<0:break
            opening=text.index('(',start);depth=1;i=opening+1
            while depth:
                depth+=(text[i]=='(')-(text[i]==')');i+=1
            expression=text[opening+1:i-1]
            block=text[i:text.find('}',i)+1]
            if 'SetRecoveryFamily(owner->recoveryFamily)' in block:found.append(expression)
            start=i
        assert len(found)==1,(marker,len(found))
        result.append(found[0])
    return result


def main():
    out=Path(os.environ['FSRD_GPU_TEST_OUTPUT']).resolve();out.mkdir(parents=True,exist_ok=True)
    coordinator=Path(os.environ.get('FSRD_ANCHOR_FAMILY_COORDINATOR',str(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp')))
    source=coordinator.read_bytes();converted,rr=source_gates(source)
    header='bool ConvertedFamilyGate(bool succeeded,const RRSettings& rrSettings){return '+converted+';}\n'
    header+='bool NativeFamilyGate(bool prepared,const RRSettings& settings){struct Stage{RRSettings settings;};Stage value{settings};const auto* stage=&value;return '+rr+';}\n'
    (out/'source_family_gates.h').write_bytes(header.encode('utf-8'))
    os.environ.update(FSRD_NATIVE_ANCHOR_FIXTURE_CPP=str(HERE/'fsrd_nrd_anchor_shared_family.cpp'),FSRD_NATIVE_ANCHOR_BUILD_ONLY='1')
    native.main()
    exe=out/'native-post-motion-anchor.exe'
    run=subprocess.run([str(exe),str(out)],capture_output=True,text=True,timeout=120)
    (out/'stdout.log').write_text(run.stdout);(out/'stderr.log').write_text(run.stderr)
    if run.returncode:print(run.stderr,flush=True)
    run.check_returncode();assert 'PASS native_anchor_shared_family checks=' in run.stdout
    mutant=subprocess.run([str(exe),str(out/'legacy_gate_mutant'),'--legacy-gate-mutant'],capture_output=True,text=True,timeout=120)
    (out/'mutant.stdout.log').write_text(mutant.stdout);(out/'mutant.stderr.log').write_text(mutant.stderr)
    assert mutant.returncode!=0 and 'actual anchor domain uses Service family' in mutant.stderr,mutant.stderr
    assert coordinator.read_bytes()==source,'coordinator changed during proof'
    result=json.loads((out/'shared_family_result.json').read_text())
    result.update(passed=True,coordinator=str(coordinator),coordinator_sha256=sha(source),
        extracted_predicates=[converted,rr],generated_header_sha256=sha(header.encode()),required_legacy_mutant_failure=True)
    (out/'family_policy_manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(run.stdout,flush=True);print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
