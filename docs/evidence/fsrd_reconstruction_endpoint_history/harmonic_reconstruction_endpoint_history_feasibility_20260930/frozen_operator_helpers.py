from pathlib import Path
import json,hashlib
import numpy as np
import model
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def descriptor(freq=(3.23,1.17),chosen=(0,1,2)):
    return dict(frequencies=[list(freq)],chosen=list(chosen),groups=[list(range(1,len(chosen)))],original_groups=[[1,2]])
def physical(desc,h,w):return model.physical_projection(desc,h,w)['Phi']
def source_records(n,desc,theta=0.,used=False):
    return dict(frames=[dict(frame=i,epoch_start=0,atom_frequencies=desc['frequencies'] if desc else [],
        atom_diagnostics=[] if desc is None else [dict(phase_increment=theta,phase_used=used,innovation=False)]) for i in range(n)])
