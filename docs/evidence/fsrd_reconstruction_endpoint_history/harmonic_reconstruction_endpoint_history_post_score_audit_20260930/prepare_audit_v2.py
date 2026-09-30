"""Preserve first independent audit assembly failure and repair only report naming."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
HERE=Path(__file__).resolve().parent
def ident(p):return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
src=(HERE/'audit.py').read_text()
assert src.count("compact=read(END/'compact_report.json')")==1
new=src.replace("compact=read(END/'compact_report.json')","producer_compact=read(END/'compact_report.json')").replace("compact['counts']","producer_compact['counts']")
new=new.replace("save('preregistration.json'","save('preregistration_v2.json'").replace("save('frozen_scorer_ast_extraction.json'","save('frozen_scorer_ast_extraction_v2.json'")
new=new.replace("CPU_saved_array_metric_dicts=checks['recomputed_native_metric_dicts']","CPU_saved_array_metric_dicts=checks['recomputed_native_metric_dicts'],prior_incomplete_attempt_metric_dicts=18,total_actual_metric_dict_recomputations_across_attempts=checks['recomputed_native_metric_dicts']+18")
with(HERE/'audit_v2.py').open('x',encoding='utf-8',newline='\n')as f:f.write(new)
qualification=dict(schema='independent-post-score-audit-assembly-failure-qualification-v1',UTC=datetime.now(timezone.utc).isoformat(),
    issue='Local report variable compact shadowed the compact() function. Material18 metric dictionaries and prior-comparator checks passed before UnboundLocalError during summary construction; no result audit was sealed.',
    scope='Only independent auditor report assembly changed. Exact saved data, scorer function ASTs and quality gates unchanged. Original script, actual run.log, preregistration and extraction bytes preserved.',
    repair='Rename local compact_report record to producer_compact; fresh audit_v2.py and separate v2 metadata filenames. No producer/model/analyzer/result modification or execution.',
    prior_actual_metric_dict_recomputations=18,prior_native_GPU_model_analyzer_build_calls=0,
    preserved_attempt1=[ident(HERE/n)for n in('audit.py','run.log','preregistration.json','frozen_scorer_ast_extraction.json')])
with(HERE/'audit_attempt1_qualification.json').open('x',encoding='utf-8',newline='\n')as f:json.dump(qualification,f,indent=2);f.write('\n')
print(json.dumps({'status':'audit_v2_report_assembly_repair_only','source':ident(HERE/'audit_v2.py')}))
