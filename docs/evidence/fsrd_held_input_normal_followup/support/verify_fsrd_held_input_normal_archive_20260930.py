"""Check compact evidence against every staged Git blob, without normalization."""
from pathlib import Path
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'docs/evidence/fsrd_held_input_normal_followup'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    manifest=json.loads((folder/'manifest.json').read_text())
    paths=[folder/row['path'] for row in manifest['archived_files']]+[folder/'manifest.json',folder/'.gitattributes']
    wanted={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in paths}
    for row in manifest['archived_files']:
        if sha(folder/row['path'])!=row['sha256']:raise ValueError('Archive identity mismatch')
    request=''.join(':'+p+'\n' for p in wanted).encode()
    raw=subprocess.check_output(['git','cat-file','--batch'],input=request,cwd=ROOT);offset=0
    for path,expected in wanted.items():
        end=raw.index(b'\n',offset);header=raw[offset:end].split();offset=end+1
        if len(header)!=3 or header[1]!=b'blob':raise ValueError('Missing staged blob '+path)
        size=int(header[2]);blob=raw[offset:offset+size];offset+=size+1
        if hashlib.sha256(blob).hexdigest()!=expected:raise ValueError('Staged byte mismatch '+path)
    if offset!=len(raw):raise ValueError('Unparsed staged bytes')
    result=dict(schema='staged-held-input-normal-archive-byte-check-v1',files=len(wanted),all_staged_hashes_equal=True,
                manifest_sha256=sha(folder/'manifest.json'),verifier_sha256=sha(__file__))
    (ROOT/'tools_tmp/held_input_normal_staged_verification_20260930.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
if __name__=='__main__':main()
