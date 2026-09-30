"""Read-only return hook, never alters the selected source model or algorithm."""
from pathlib import Path
import hashlib,importlib.util,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'tools_tmp/source_continuous_harmonic_feasibility_20260930/harmonic_pilot.py'
PIN='be66624153a286c6b3299735fc2a1bbf5162ffe24a52d7f9421d1c4b90a52173'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def capture(raw,controls,exposure=None,verify=True):
    assert sha(SOURCE)==PIN
    original=load('untouched_physical_source',SOURCE)
    instrumented=load('read_only_selected_columns',SOURCE)
    selected=[];function=instrumented.select_model
    def wrapped(*args,**kwargs):
        result=function(*args,**kwargs);model=result[0]
        selected.append(None if model is None else dict(frequencies=model['freqs'],chosen=model['chosen'],
            groups=model['groups'],original_groups=model['original_groups']))
        return result
    instrumented.select_model=wrapped
    P,a,d=instrumented.make_continuous_harmonic_pilot(raw,controls,exposure)
    if verify:
        plain,pa,pd=original.make_continuous_harmonic_pilot(raw,controls,exposure)
        assert P.tobytes()==plain.tobytes() and a.tobytes()==pa.tobytes() and d==pd
    descriptors=[];current=None;cursor=0
    for rec in d['frames']:
        if rec['selection'] is not None:current=selected[cursor];cursor+=1
        descriptors.append(current if rec['atom_frequencies'] else None)
    assert cursor==len(selected)
    return P,a,d,descriptors
