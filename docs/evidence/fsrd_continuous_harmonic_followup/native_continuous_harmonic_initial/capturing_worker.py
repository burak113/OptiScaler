"""Retain actual GPU job bytes/logs before the existing helper removes them."""
from pathlib import Path
import hashlib,json,shutil
from fsrd_alpha_common import GPUWorker

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
class CapturingGPUWorker(GPUWorker):
    def __init__(self,output):
        self.capture=Path(output)/'persisted_shader_jobs';self.capture.mkdir()
        self.entries=[]
        super().__init__(output)
    def run(self,args,**kwargs):
        completed=super().run(args,**kwargs)
        if str(args[0])!=str(self.worker.args[0]):return completed
        job=Path(args[1]);destination=self.capture/job.parent.name
        destination.mkdir();files=[]
        for p in sorted(job.parent.iterdir()):
            if p.is_file() and (p.suffix=='.bin' or p.name=='job.txt'):
                before=sha(p);target=destination/p.name;shutil.copyfile(p,target)
                if sha(p)!=before or sha(target)!=before:raise ValueError('GPU job snapshot changed bytes')
                files.append(dict(name=p.name,size=p.stat().st_size,sha256=before))
        log=destination/'runner.log';log.write_text(completed.stdout,encoding='utf-8')
        self.entries.append(dict(job_name=job.parent.name,files=files,runner_log_sha256=sha(log),
            returncode=completed.returncode,actual_run_completed=True))
        (self.capture/'manifest.json').write_text(json.dumps(dict(schema='before-cleanup-actual-gpu-job-snapshot-v1',
            source_sha256=sha(__file__),jobs=self.entries),indent=2)+'\n')
        return completed
