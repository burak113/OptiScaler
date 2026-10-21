"""Apply the exact host proposal only to a temporary frozen source copy."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import tempfile
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[4]


def sha(data): return hashlib.sha256(data).hexdigest()


def verify():
    m=json.loads((HERE/'patch_manifest.json').read_text(encoding='utf-8'))
    assert sha((HERE/'integration.patch').read_bytes())==m['patch_sha256']
    before={p:sha((REPO/p).read_bytes()) for p in m['files']}
    results={}
    with tempfile.TemporaryDirectory(prefix='astra10-patch-') as scratch:
        root=Path(scratch)
        for relative,hashes in m['files'].items():
            data=subprocess.check_output(['git','show',m['base_commit']+':'+relative],cwd=REPO)
            assert sha(data)==hashes['base_sha256'],relative
            target=root/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
        for extra in (['--check'],[]):
            result=subprocess.run(['git','apply',*extra,str(HERE/'integration.patch')],cwd=root,
                                  capture_output=True,text=True)
            assert result.returncode==0,result.stdout+result.stderr
        for relative,hashes in m['files'].items():
            data=(root/relative).read_bytes()
            assert sha(data)==hashes['proposed_sha256'],relative
            results[relative]=sha(data)
        ET.fromstring((root/'OptiScaler/OptiScaler.vcxproj').read_bytes())
        source=(root/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp').read_text()
        # Source-location sanity supplements (never replaces) native build/run.
        start=source.index('bool RRWrapper::RecordOwnedImpl')
        prep=source.index('ColourPass::Prepare',start)
        retain=source.index('RetainComputeDispatch',start)
        provider=source.index('FfxApiProxy::D3D12_Dispatch',start)
        selected=source.index('flatAlbedo->RecordOutput',provider)
        record=source.index('ColourPass::Record(',selected)
        publish=source.index('output = std::move(recorded)',record)
        assert start<prep<retain<provider<selected<record<publish
        assert 'SetCommitInputs(*lease->slot,committedSpec,committedDiff)' in source[record:publish]
        assert 'recorded->selectedSpec = committedSpec; recorded->selectedDiff = committedDiff;' in source[record:publish]
    after={p:sha((REPO/p).read_bytes()) for p in m['files']}
    assert before==after,'production source changed during verification'
    return dict(passed=True,base_commit=m['base_commit'],patch_sha256=m['patch_sha256'],
        proposed_files=results,production_files_unchanged=True,
        patch_applied_only_in_temporary_copy=True,windows_compile_executed=False,gpu_executed=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    result=verify()
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
