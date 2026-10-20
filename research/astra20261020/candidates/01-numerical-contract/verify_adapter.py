"""Apply the proposed production patch to a clean temporary source copy."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[3]


def verify():
    identity=json.loads((HERE/'adapter/adapter_identity.json').read_text())
    relative=identity['source_path']
    original=subprocess.check_output(['git','show','astra-handoff-20261020:'+relative],cwd=REPO)
    assert hashlib.sha256(original).hexdigest()==identity['base_source_sha256']
    assert (REPO/relative).read_bytes()==original,'production source changed in working checkout'
    with tempfile.TemporaryDirectory(prefix='numerical_contract_adapter_') as tmp:
        root=Path(tmp);target=root/relative;target.parent.mkdir(parents=True)
        target.write_bytes(original)
        patch=HERE/'adapter/PRODUCTION.patch'
        subprocess.run(['git','apply','--check',str(patch)],cwd=root,check=True,capture_output=True)
        subprocess.run(['git','apply',str(patch)],cwd=root,check=True,capture_output=True)
        assert target.read_bytes()==(HERE/'adapter/FSRDColourTrackTrack.hlsl').read_bytes()
        assert hashlib.sha256(target.read_bytes()).hexdigest()==identity['proposed_source_sha256']
    return {'base_source_identity_verified':True,'clean_copy_patch_check_exit_code':0,
            'clean_copy_patch_apply_exit_code':0,'patched_bytes_match_candidate_hlsl':True,
            'production_source_unchanged':True,'dxc_compiled':False,'gpu_executed':False}


if __name__=='__main__':print(json.dumps(verify(),indent=2))
