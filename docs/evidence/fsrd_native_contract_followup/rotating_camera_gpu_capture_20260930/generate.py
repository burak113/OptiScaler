"""Derive an exact-protocol camera repeat with actual job retention."""
from pathlib import Path
import hashlib,json
folder=Path(__file__).resolve().parent;parent=folder.parent/'rotating_camera_gpu_conformance_20260930/analyze.py';target=folder/'analyze.py'
if target.exists():raise ValueError('Preserve derived capture repeat')
text=parent.read_text()
changes=(
    ('from fsrd_alpha_common import GPUWorker,convert,shader_identity','from fsrd_alpha_common import convert,shader_identity\nfrom capturing_worker import CapturingGPUWorker as GPUWorker'),
    ("schema='rotating-camera-four-conversion-gpu-conformance-v1'","schema='rotating-camera-four-conversion-retained-job-conformance-v1'"),
    ('all_pixel_motion_within_one_ulp_plus_1e5','all_pixel_motion_within_one_ulp_plus_1e_minus_5'),
    ("    result['comparisons']=[]", "    result['captured_jobs_manifest_sha256']=sha(out/'persisted_shader_jobs/manifest.json')\n    result['capture_worker_sha256']=sha(Path(__file__).with_name('capturing_worker.py'))\n    result['comparisons']=[]"),
)
for old,new in changes:
    if text.count(old)!=1:raise ValueError('Capture source anchor')
    text=text.replace(old,new,1)
target.write_text(text,encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(folder/'source_derivation.json').write_text(json.dumps(dict(parent=str(parent),parent_sha256=sha(parent),derived_script_sha256=sha(target),
    generator_sha256=sha(Path(__file__)),capture_worker_sha256=sha(folder/'capturing_worker.py'),
    changed='Same four fixture/PSO conversion calls. After native server completion but before helper cleanup, retain all job CB/input/output bytes and stdout; correct metadata key spelling1e-5. No algorithm/production change.'),indent=2)+'\n')
