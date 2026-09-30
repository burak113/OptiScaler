"""CPU-only immutable V1 reference checks before V2 continuation seal exists."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/tools_tmp')
P=ROOT/'fsrd_native_gap_cpu_record_control_20260930';OUT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ident(p):p=Path(p);return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def load(p):return json.loads(Path(p).read_text())
partial=P/'partial_v1_completion_manifest.json'
assert sha(partial)=='82b78b5c6628eae7c44afd23d492b6ccd43f6ab5a47e79142dde9c16c5f1eab2'
m=load(partial)
for records in [m['files'],m.get('external_sources',[])]:
    for r in records:assert ident(r['path'])==r,r['path']
r=load(P/'evidence/results.json');reg=load(P/'registration.json')
assert r['status']=='failed_preserved'
assert [r[k]for k in ['completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','no_API_omissions','metadata_accepted_native_contexts']]==[2,127,126,1,1,1]
pending=[c for c in reg['cases']if c['tag']not in r['cases']]
assert len(pending)==6
for c in pending:
    for n in ['resource_guard.json','stdout.log','stderr.log','diffuse.bin','specular.bin','native_work_accounting.json']:
        assert not(P/'evidence'/c['tag']/n).exists()
assert [sum(c[k]for c in pending)for k in ['frames_recorded','frames_queued','frames_discarded','frames_omitted_API']]==[381,378,3,3]
out={'schema':'gap-V2-continuation-preliminary-independent-checklist-v1','UTC':datetime.now(timezone.utc).isoformat(),
 'status':'V1_reference_authenticated_V2_final_seal_pending_not_ready','new_GPU_native_build_calls':0,
 'V1_partial_seal':ident(partial),'V1_results':ident(P/'evidence/results.json'),
 'V1_real_work':[2,127,126,1,1],'V1_original_metadata_accepted_contexts':1,
 'remaining_six_have_not_run':True,'pending_tags':[c['tag']for c in pending],
 'required_final_checks':['Original CPP/EXE/56 input files/control bytes remain frozen. Only unused six cases launch; first two guards prohibit rerun.',
  'Separate unique V2 results target and explicit posthoc admissibility chronology; original failed V1 report untouched.',
  'NoAPI permits SDK warning count0 or1; count1 requires exactly Frame index jump detected. Resetting... line. Record-discard requires0. All D3D errors/warnings and SDK errors0.',
  'Actual stage accounting checkpoint before diagnostic/metadata rejection and after guard exception; trustworthy bounded footer authoritative, missing footer lower bounds unknown.',
  'Posthoc diagnostic admissibility is not quality acceptance and cannot retroactively label eight V1 zero-warning successes.'],
 'causal_scope':'Synthetic wave, static camera/jitter and this provider/device/context. Unframed warning may mediate tail reset but exact emitting API call is not logged; no universal contract/game quality cause.',
 'quality_accepted':False}
with(OUT/'preliminary_review.json').open('x',encoding='utf-8',newline='\n')as f:json.dump(out,f,indent=2);f.write('\n')
print(json.dumps(ident(OUT/'preliminary_review.json')))
