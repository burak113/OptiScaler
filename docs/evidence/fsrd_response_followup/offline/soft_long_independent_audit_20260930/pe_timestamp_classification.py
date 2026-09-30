import hashlib,json,struct
from pathlib import Path
HERE=Path(__file__).resolve().parent
r=json.loads((HERE/'pe_audit.json').read_text())
masked=[];fields=[]
for binary in r['binaries']:
    data=bytearray(Path(binary['path']).read_bytes())
    nt=struct.unpack_from('<I',data,0x3c)[0]
    coff_timestamp=nt+8
    debug=next(x for x in binary['directories'] if x['index']==6)
    section=next(x for x in binary['sections'] if x['rva']<=debug['rva']<x['rva']+max(x['virtual_size'],x['raw_size']))
    debug_base=section['raw_offset']+debug['rva']-section['rva']
    timestamp_offsets=[coff_timestamp]+[debug_base+i*28+4 for i in range(debug['size']//28)]
    covered={i for offset in timestamp_offsets for i in range(offset,offset+4)}
    assert set(r['different_file_offsets'])<=covered
    fields.append(dict(binary_sha256=binary['sha256'],timestamp_offsets=timestamp_offsets,
        timestamp_values=[struct.unpack_from('<I',data,offset)[0] for offset in timestamp_offsets]))
    for offset in timestamp_offsets:data[offset:offset+4]=b'\0'*4
    masked.append(bytes(data))
assert masked[0]==masked[1]
result=dict(schema='PE-timestamp-field-classification-v1',source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    pe_audit_sha256=hashlib.sha256((HERE/'pe_audit.json').read_bytes()).hexdigest(),fields=fields,
    whole_files_identical_after_zeroing_only_coff_and_debug_timestamps=True,
    normalized_file_sha256=hashlib.sha256(masked[0]).hexdigest(),
    differing_bytes_exclusively_timestamp_fields=True,
    interpretation='Compiled runner bytes differ exclusively in COFF and IMAGE_DEBUG_DIRECTORY timestamps. Code, static data, imports and debug payload match. This binary characterization does not explain native context variation or identify a caller defect.')
p=HERE/'pe_timestamp_classification.json';assert not p.exists()
p.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result));print('report_sha256',hashlib.sha256(p.read_bytes()).hexdigest())
