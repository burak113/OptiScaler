"""Byte-copy pinned CPU accounting core and adapt only analysis identity strings."""
from pathlib import Path
import difflib,hashlib,json
HERE=Path(__file__).resolve().parent;PRIOR=HERE.parent/'fsrd_native_discarded_recording_diagnostic_20260930'
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def main():
    core=PRIOR/'native_work_accounting_v3.py';assert identity(core)['sha256']=='a203c59afabe20c1cb49c3ad76d7d0330099eae6216cc49f812c95604aea56b4'
    with(HERE/'native_work_accounting_core_v3.py').open('xb')as f:f.write(core.read_bytes())
    source=PRIOR/'analyze.py';text=source.read_text();changes=[]
    for before,after in(('completed_H2_native_record_discard_diagnostic_not_solution','completed_matched_gap_CPU_record_diagnostic_not_solution'),('discarded-record-H2-descriptive-raw-comparisons-v1','matched-gap-CPU-record-descriptive-raw-comparisons-v1')):
        assert text.count(before)==1;text=text.replace(before,after);changes.append({'before':before,'after':after})
    with(HERE/'analyze.py').open('x',encoding='utf-8',newline='\n')as f:f.write(text)
    with(HERE/'analysis_adaptation.diff').open('x',encoding='utf-8',newline='\n')as f:f.write(''.join(difflib.unified_diff(source.read_text().splitlines(keepends=True),text.splitlines(keepends=True),fromfile='pinned_H2_analyzer',tofile='matched_gap_analyzer')))
    with(HERE/'CPU_tool_source_whitelist.json').open('x',encoding='utf-8',newline='\n')as f:json.dump({'core_source':identity(core),'copied_core':identity(HERE/'native_work_accounting_core_v3.py'),'analysis_source':identity(source),'new_analysis':identity(HERE/'analyze.py'),'analysis_replacements':changes},f,indent=2);f.write('\n')
    print('Pinned accounting core copied and analysis identity adapted; no native execution.')
if __name__=='__main__':main()
