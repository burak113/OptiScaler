from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, struct, re

ROOT = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
P = ROOT / 'tools_tmp/fsrd_compute_ring_deferred_gpu_20260930'
OUT = Path(__file__).resolve().parent
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):
    p=Path(p); return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def section(s, start, end):
    a=s.index(start); return s[a:s.index(end,a)+len(end)]
def save(name, value):
    with (OUT/name).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,indent=2,allow_nan=False); f.write('\n')
def root_words(b):
    def words(offset,n): return struct.unpack_from('<'+'I'*n,b,offset)
    ver,np,po,ns,so,flags=words(0,6)
    params=[]
    for i in range(np):
        kind,vis,offset=words(po+12*i,3)
        p={'index':i,'type':kind,'visibility':vis}
        if kind==2:
            reg,space=words(offset,2); p.update(register=reg,space=space,flags=words(offset+8,1)[0] if ver==2 else None)
        elif kind==0:
            n,base=words(offset,2); ranges=[]
            for j in range(n):
                v=words(base+j*(24 if ver==2 else 20),6 if ver==2 else 5)
                ranges.append({'type':v[0],'count':v[1],'base_register':v[2],'space':v[3],
                               'flags':v[4] if ver==2 else None,'offset':v[5] if ver==2 else v[4]})
            p['ranges']=ranges
        else: raise AssertionError('unexpected parameter type')
        params.append(p)
    return {'version_enum':ver,'root_flags':flags,'parameters':params,'static_samplers':ns}
def root_from_shader(b):
    assert b[:4]==b'DXBC' and struct.unpack_from('<I',b,24)[0]==len(b)
    n=struct.unpack_from('<I',b,28)[0]; found=[]
    for off in struct.unpack_from('<'+'I'*n,b,32):
        size=struct.unpack_from('<I',b,off+4)[0]
        if b[off:off+4]==b'RTS0': found.append(b[off+8:off+8+size])
    assert len(found)==1; return found[0]

reg=json.loads((P/'registration.json').read_text())
freeze=json.loads((P/'pre_gpu_freeze.json').read_text())
for item in freeze['files']+freeze['original_sources']:
    assert identity(item['path'])==item, item['path']
producer_report_exists=(P/'evidence/results.json').exists()
prod=(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp').read_text()
compute=section(prod,'struct ComputeState\n','\n};')
heap=section((ROOT/'OptiScaler/shaders/Shader_Dx12Utils.h').read_text(),'class FrameDescriptorHeap\n','\n};')
utils=(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDShaderUtils.h').read_text()
a=utils.index('    constexpr UINT kMaxBarriers'); b=utils.index('    /**\n     * @brief Calculates normalized 1D Gaussian weights',a)
assert (P/'exact_ComputeState.h').read_text()==compute+'\n'
assert (P/'exact_FrameDescriptorHeap.h').read_text()==heap+'\n'
assert (P/'exact_helpers.h').read_text()==utils[a:b]
split=compute.replace('struct ComputeState','struct SplitComputeState').replace('~ComputeState()','~SplitComputeState()')
split=split.replace('    UINT backBufferCount = kBackBufferCount;',
                    '    UINT backBufferCount = kBackBufferCount;\n    UINT diagnosticCbSlots=3, diagnosticDescriptorSlots=3;')
split=split.replace('        const UINT currentFrame = m_cbCurrentFrameIndex;',
                    '        const UINT currentFrame = m_cbCurrentFrameIndex % diagnosticCbSlots;\n        const UINT descriptorFrame = m_cbCurrentFrameIndex % diagnosticDescriptorSlots;')
split=split.replace('FrameDescriptorHeap& currentHeap = m_frameHeaps[currentFrame];',
                    'FrameDescriptorHeap& currentHeap = m_frameHeaps[descriptorFrame];')
adapted=(P/'production_extract.h').read_text()
assert adapted[adapted.index('struct SplitComputeState\n'):]==split+'\n'
rs=json.loads((P/'root_signatures.json').read_text())
root_rows=[]
for recorded in rs['signatures'] if 'signatures' in rs else rs['actual_serialized_root_signatures']:
    blob=root_from_shader(Path(recorded['shader']['path']).read_bytes())
    assert blob==Path(recorded['root_blob']['path']).read_bytes()
    decoded=root_words(blob)
    assert all(recorded[k]==v for k,v in decoded.items())
    for entry in (recorded['shader'],recorded['root_blob']): assert identity(entry['path'])==entry
    root_rows.append({'name':recorded['name'],**decoded})
assert root_rows[0]['version_enum']==1
assert all(r['version_enum']==2 for r in root_rows[1:])
case_rows=[]
for c in reg['cases']:
    n=c['shader_dispatches']; mc=c['cb_slots']; ms=c['descriptor_slots']
    assert 1<=n<=5
    cb={};srv={}
    for j in range(n): cb[j%mc]=j; srv[j%ms]=j
    rows=[]
    for j in range(n):
        a=j if c['fence_before_reuse'] else cb[j%mc]
        b=j if c['fence_before_reuse'] else srv[j%ms]
        rows.append([100+a,5000+b,200+a,0xD1A60001])
    assert rows==c['last_CPU_slot_contents_hypothesis']
    assert c['intended']==[[100+j,5000+j,200+j,0xD1A60001] for j in range(n)]
    job=list(map(int,(P/'evidence'/c['case']/'job.txt').read_text().split()))
    assert job==[n,mc,ms,int(c['fence_before_reuse']),int(c['class']=='SplitComputeState')]
    case_rows.append({'case':c['case'],'independent_last_write_prediction':rows})
assert len(case_rows)==9 and sum(c['shader_dispatches'] for c in reg['cases'])==40
fixture=(P/'fixture.cpp').read_text()
fenced=fixture.index('if(fenced&&i>0&&i%cbSlots==0)')
dispatch=fixture.index('if(split)factors.Dispatch',fenced)
copy=fixture.index('cmd->CopyTextureRegion',dispatch)
finalwait=fixture.index('executeWait();trace<<"completed_final',copy)
mapread=fixture.index('readbacks[i].resource->Map',finalwait)
assert fenced<dispatch<copy<finalwait<mapread
assert 'dst.pResource=readbacks[i].resource.Get()' in fixture
assert 'transition(cmd.Get(),output.Get(),kUavState,D3D12_RESOURCE_STATE_COPY_SOURCE)' in fixture
assert 'transition(cmd.Get(),output.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,kUavState)' in fixture
assert 'executeWait();reset(); // All distinct inputs immutable' in fixture
report={
 'schema':'independent-compute-ring-source-review-v1','utc':datetime.now(timezone.utc).isoformat(),
 'status':'source_review_passed_with_scope_qualifications','GPU_report_accepted':False,
 'own_GPU_native_build_calls':0,'producer_report_exists_at_final_source_artifact':producer_report_exists,
 'chronology':'Preliminary/root-semantics artifacts and source-reading findings preceded the reported GPU completion. Final exact-extraction/parser artifact is generated after producer GPU completion; it is not a prelaunch approval record. Actual results are not yet independently accepted.',
 'registration':identity(P/'registration.json'),'pre_gpu_freeze':identity(P/'pre_gpu_freeze.json'),
 'frozen_file_entries_checked':len(freeze['files']),'original_source_entries_checked':len(freeze['original_sources']),
 'exact_extractions_verified':['ComputeState','FrameDescriptorHeap','FSRDShaderUtils helper slice'],
 'split_index_whitelist_verified':True,'actual_roots_independently_parsed_from_shader_RTS0':root_rows,
 'case_predictions':case_rows,
 'binding_semantics':'Root CBV stores GPU virtual address; descriptor table stores heap GPU handle. Neither snapshots mapped CB bytes or SRV descriptor contents. Forced1.0 permits controlled edits after recording and before submission; fixture never modifies submitted bindings before completion.',
 'output_capture':'Stable single UAV; each Dispatch is followed by UAV-to-copy-source transition, unique ordinal-indexed CopyTextureRegion, then transition back. Maps occur only after final completion fence. Mutable CB marker cannot choose readback destination.',
 'fenced_control':'executeWait/reset occurs before Dispatch overwrites first reused slot at ordinal3. Input upload and allocator reset are completion-fenced. Allocator resets and object destruction occur after completion.',
 'adaptation_boundaries':[
  'Exact extraction is implementation text, not production runtime execution. No-op heap-capture suppression and logging/release shims remove runtime hook dependencies.',
  'Identity shader is1x1 integer,16-byte CB,one SRV/one UAV with production root parameter kinds/order; shader math, texture dimensions, queue scheduling and native provider are different.',
  'Split class allocation max5 happens before heap initialization; bounded first N<=5 selections are correct. Counter wraps allocation size, so this is not an independent-ring implementation for arbitrary N>5.',
  'Actual production header roots are1.1 with rootCBV/range flags0; default static descriptors must remain unchanged from binding through completion. A fixture1.0 alias result is not a defined outcome for production1.1 contract violations.',
  'Normal debug layer only; GPU-based validation disabled. Every actual message and guard status must be reviewed after GPU completion.'
 ],
 'quality_accepted':False,'actual_game_trigger_proven':False,'actual_GPU_validation_pending':True,
 'source_pins':[identity(P/n) for n in ['prepare.py','fixture.cpp','identity.hlsl','identity.cso','fixture.exe','production_extract.h','exact_ComputeState.h','exact_FrameDescriptorHeap.h','exact_helpers.h','root_inspector.cpp','root_signatures.json','run_gpu.py']],
 'reference':'https://learn.microsoft.com/en-us/windows/win32/direct3d12/root-signature-version-1-1'
}
save('source_review.json',report)
save('source_review_manifest.json',{'files':[identity(p) for p in sorted(OUT.iterdir()) if p.is_file()]})
print(json.dumps({'source_review':identity(OUT/'source_review.json'),'manifest':identity(OUT/'source_review_manifest.json'),'producer_report_exists_at_final_source_artifact':producer_report_exists}))
