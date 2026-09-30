"""Compare immutable compact archive bytes against staged Git blobs."""
from pathlib import Path
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'docs/evidence/fsrd_phase_response_followup'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    manifest=json.loads((FOLDER/'manifest.json').read_text())
    paths=[FOLDER/r['path'] for r in manifest['archived_files']]+[FOLDER/'manifest.json',FOLDER/'.gitattributes']
    wanted={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    for row in manifest['archived_files']:
        assert sha(FOLDER/row['path'])==row['sha256'] and sha(row['source'])==row['sha256']
    raw=subprocess.check_output(['git','cat-file','--batch'],input=''.join(':'+p+'\n' for p in wanted).encode(),cwd=ROOT);offset=0
    for path,expected in wanted.items():
        end=raw.index(b'\n',offset);header=raw[offset:end].split();offset=end+1
        if len(header)!=3 or header[1]!=b'blob':raise ValueError('Missing staged blob '+path)
        size=int(header[2]);blob=raw[offset:offset+size];offset+=size+1
        if hashlib.sha256(blob).hexdigest()!=expected:raise ValueError('Staged bytes differ '+path)
    assert offset==len(raw)
    result=dict(schema='staged-phase-response-archive-byte-check-v1',files=len(wanted),all_staged_hashes_equal=True,
        manifest_sha256=sha(FOLDER/'manifest.json'),verifier_sha256=sha(__file__))
    (ROOT/'tools_tmp/phase_response_staged_verification_20260930.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
if __name__=='__main__':main()
