"""Derive one-control diagnostic from the pinned source-repeat implementation."""
from pathlib import Path
import hashlib,json
folder=Path(__file__).resolve().parent
source=folder.parent/'controlled_context_repeat_20260930/analyze.py'
target=folder/'analyze.py'
if target.exists():raise ValueError('Preserve prior generated diagnostic')
text=source.read_text();changes=(
    ("schema='pinned-runner-native-context-repeat-v1'", "schema='pinned-runner-transition-reset-repeat-v1'"),
    ("'No output clearing or caller/provider algorithm change; earlier divergent contexts remain evidence.'", "'Only frame32 RESET differs; no output clearing, binary or provider change; earlier divergences remain evidence.'"),
    ("summary['input_authentication']=authenticate_reused_source(case/'observed',packed,data['depth'],controls,checks);save()", "summary['input_authentication']=authenticate_reused_source(case/'observed',packed,data['depth'],controls,checks);save()\n        controls=controls.copy();controls[32,0]=1\n        applied_original=(case/'observed/dispatch_controls.bin').read_bytes()"),
    ("'inputs','applied_dispatch_sha256','dll_sha256'", "'inputs','dll_sha256'"),
    ("            halves={'diffuse'", "            applied=(folder/'dispatch_controls.bin').read_bytes()\n            expected=bytearray(applied_original)\n            flags=np.frombuffer(applied_original,dtype='<u4',count=1,offset=32*184+4)[0]\n            expected[32*184+4:32*184+8]=np.array([flags|1],dtype='<u4').tobytes()\n            if applied!=bytes(expected):raise ValueError('Applied reset diagnostic changed other fields')\n            halves={'diffuse'"),
)
for old,new in changes:
    if text.count(old)!=1:raise ValueError('Ambiguous diagnostic source anchor')
    text=text.replace(old,new,1)
target.write_text(text,encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(folder/'source_derivation.json').write_text(json.dumps(dict(source=str(source),source_sha256=sha(source),generated_sha256=sha(target),
    generator_sha256=sha(Path(__file__)),only_control_change='RESET at frame32; applied bytes verified'),indent=2)+'\n')
