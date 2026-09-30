"""Derive isolated tuning-bundle control from the preserved repeat script."""
from pathlib import Path
import ast,hashlib,json
folder=Path(__file__).resolve().parent;root=folder.parents[1]
parent=folder.parent/'controlled_context_repeat_20260930/analyze.py'
function_parent=root/'OptiScaler/shaders/shader_tools/tests/probe_fsrd_additive_split.py'
target=folder/'analyze.py'
if target.exists():raise ValueError('Preserve generated diagnostic')
node=next(v for v in ast.parse(function_parent.read_text()).body if isinstance(v,ast.FunctionDef) and v.name=='run_amd')
helper=ast.get_source_segment(function_parent.read_text(),node)
changes=(
    ('{w} {h} {n} 2 32 0 1 0','{w} {h} {n} 2 32 0 0 0'),
    ('reset_every=0,tuning=1,passthrough=0','reset_every=0,tuning=0,passthrough=0'),
    ('tuning_values=[.1,.5,.5,40000.,40.,.5]','tuning_values=[], effect_key_configure_count=0, global_debug_configure=True'),
)
for old,new in changes:
    if helper.count(old)!=1:raise ValueError('Native helper derivation anchor')
    helper=helper.replace(old,new,1)
hp=folder/'native_helper.py';hp.write_text('from pathlib import Path\nfrom probe_fsrd_additive_split import DLL,write_texture,save_json\nimport numpy as np\nimport re,json,hashlib,subprocess\n'+helper+'\n',encoding='utf-8')
text=parent.read_text()
changes=(
    ('from probe_fsrd_additive_split import run_amd,DLL','from probe_fsrd_additive_split import DLL\nfrom native_helper import run_amd'),
    ("schema='pinned-runner-native-context-repeat-v1'","schema='pinned-runner-default-tuning-context-repeat-v1'"),
    ("'No output clearing or caller/provider algorithm change; earlier divergent contexts remain evidence.'","'Only tuning flag1->0 skips six effect overrides; no output clearing/binary/provider change. Earlier divergence remains evidence.'"),
    ("    def save():", "    query=ROOT/'tools_tmp/provider_defaults_query_20260930/evidence/results.json'\n    summary['separate_default_query']=dict(path=str(query),sha256=sha(query),keys=json.loads(query.read_text())['keys'],not_queried_by_pinned_runner=True)\n    summary['native_helper_sha256']=sha(Path(__file__).with_name('native_helper.py'))\n    summary['source_derivation_sha256']=sha(Path(__file__).with_name('source_derivation.json'))\n    def save():"),
    ("'reset_every','tuning','passthrough','tuning_values'", "'reset_every','passthrough'"),
    ("            halves={'diffuse'", "            if manifest['tuning']!=0 or manifest['tuning_values']!=[] or manifest['effect_key_configure_count']!=0:raise ValueError('Tuning bundle metadata')\n            job_header=(folder/'job.txt').read_text().splitlines()[0].split()\n            if job_header[:8]!=['128','80','64','2','32','0','0','0']:raise ValueError('Tuning control job header')\n            halves={'diffuse'"),
)
for old,new in changes:
    if text.count(old)!=1:raise ValueError('Repeat script derivation anchor')
    text=text.replace(old,new,1)
target.write_text(text,encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(folder/'source_derivation.json').write_text(json.dumps(dict(parent_script=str(parent),parent_sha256=sha(parent),
    function_parent=str(function_parent),function_parent_sha256=sha(function_parent),generated_script_sha256=sha(target),
    generated_helper_sha256=sha(hp),generator_sha256=sha(Path(__file__)),
    changed_control='Job tuning1->0 skips six effect Configure calls; metadata names no unused values as applied'),indent=2)+'\n')
