"""Read-only PE section/header/import comparison; no execution or native attribution."""
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
C = Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce')
STUDIES = [C/'response_soft_temporal_alpha_fresh', C/'response_soft_temporal_long_alpha_fresh']

def sha(value): return hashlib.sha256(value).hexdigest()

def parse(path):
    data=path.read_bytes()
    assert data[:2]==b'MZ'
    nt=struct.unpack_from('<I',data,0x3c)[0]
    assert data[nt:nt+4]==b'PE\0\0'
    machine,count,timestamp,_,_,optional_size,characteristics=struct.unpack_from('<HHIIIHH',data,nt+4)
    optional=nt+24
    magic=struct.unpack_from('<H',data,optional)[0]
    assert magic==0x20b
    directories=[struct.unpack_from('<II',data,optional+112+i*8) for i in range(16)]
    sections=[]
    for i in range(count):
        pos=optional+optional_size+i*40
        name=data[pos:pos+8].split(b'\0')[0].decode()
        virtual_size,rva,size,offset=struct.unpack_from('<IIII',data,pos+8)
        flags=struct.unpack_from('<I',data,pos+36)[0]
        payload=data[offset:offset+size]
        sections.append(dict(name=name,virtual_size=virtual_size,rva=rva,raw_size=size,raw_offset=offset,
            characteristics=flags,sha256=sha(payload)))
    def file_offset(rva):
        for s in sections:
            if s['rva']<=rva<s['rva']+max(s['virtual_size'],s['raw_size']):
                return s['raw_offset']+rva-s['rva']
        if rva<sections[0]['raw_offset']:return rva
        raise ValueError(f'Unmapped RVA {rva:x}')
    def string(rva):
        pos=file_offset(rva);return data[pos:data.index(b'\0',pos)].decode('ascii')
    imports=[]
    if directories[1][0]:
        pos=file_offset(directories[1][0])
        while True:
            original,tstamp,chain,name,thunk=struct.unpack_from('<IIIII',data,pos)
            if not any((original,tstamp,chain,name,thunk)):break
            functions=[];p=file_offset(original or thunk)
            while True:
                value=struct.unpack_from('<Q',data,p)[0]
                if not value:break
                functions.append({'ordinal':value&0xffff} if value>>63 else {'name':string(value+2)})
                p+=8
            imports.append(dict(dll=string(name),timestamp=tstamp,functions=functions));pos+=20
    debug=[]
    if directories[6][0]:
        pos=file_offset(directories[6][0])
        for i in range(directories[6][1]//28):
            flags,tstamp,major,minor,kind,size,rva,offset=struct.unpack_from('<IIHHIIII',data,pos+i*28)
            item=dict(type=kind,timestamp=tstamp,size=size,rva=rva,file_offset=offset,sha256=sha(data[offset:offset+size]))
            if kind==2 and data[offset:offset+4]==b'RSDS':
                item.update(signature='RSDS',guid_hex=data[offset+4:offset+20].hex(),
                    age=struct.unpack_from('<I',data,offset+20)[0],pdb_path=data[offset+24:offset+size].split(b'\0')[0].decode())
            debug.append(item)
    return data,dict(path=str(path),sha256=sha(data),file_size=len(data),machine=machine,coff_timestamp=timestamp,
        characteristics=characteristics,optional_magic=magic,checksum=struct.unpack_from('<I',data,optional+64)[0],
        entrypoint_rva=struct.unpack_from('<I',data,optional+16)[0],sections=sections,
        directories=[dict(index=i,rva=x[0],size=x[1]) for i,x in enumerate(directories)],imports=imports,debug=debug)

parsed=[parse(s/'fsrd_rr_runner.exe') for s in STUDIES]
a,b=[x[1] for x in parsed]; da,db=[x[0] for x in parsed]
comparisons=[]
assert [s['name'] for s in a['sections']]==[s['name'] for s in b['sections']]
for x,y in zip(a['sections'],b['sections']):
    ba=da[x['raw_offset']:x['raw_offset']+x['raw_size']];bb=db[y['raw_offset']:y['raw_offset']+y['raw_size']]
    indices=[i for i,(u,v) in enumerate(zip(ba,bb)) if u!=v]
    comparisons.append(dict(name=x['name'],raw_bytes_equal=ba==bb,size_equal=len(ba)==len(bb),
        different_byte_count=len(indices)+abs(len(ba)-len(bb)),
        different_section_offsets=indices if len(indices)<256 else indices[:128],
        old_sha256=x['sha256'],new_sha256=y['sha256']))
all_diffs=[i for i,(u,v) in enumerate(zip(da,db)) if u!=v]
sources=[]
for filename in ('fsrd_rr_runner.cpp','fsrd_gpu_runner.cpp'):
    values=[sha((s/'source_snapshot'/filename).read_bytes()) for s in STUDIES]
    sources.append(dict(name=filename,old_sha256=values[0],new_sha256=values[1],equal=values[0]==values[1]))
result=dict(schema='runner-pe-section-readonly-audit-v1',analysis_sha256=sha(Path(__file__).read_bytes()),
    binaries=[a,b],section_comparison=comparisons,imports_equal=a['imports']==b['imports'],
    code_sections_equal=all(x['raw_bytes_equal'] for x in comparisons if x['name']=='.text'),
    different_whole_file_byte_count=len(all_diffs)+abs(len(da)-len(db)),
    different_file_offsets=all_diffs if len(all_diffs)<256 else all_diffs[:128],runner_sources=sources,
    conclusion='PE equality/differences characterize the binaries only; they do not identify the cause of native response variation. No timestamp or caller-bug attribution.')
output=Path(__file__).with_name('pe_audit.json')
assert not output.exists()
output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('imports_equal','code_sections_equal','different_whole_file_byte_count','section_comparison')}))
print('report_sha256',sha(output.read_bytes()))
