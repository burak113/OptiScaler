"""Only the child created here; no process discovery, descendants or retry."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import json, subprocess, time

class MemoryStatus(ctypes.Structure):
    _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[(n,ctypes.c_uint64) for n in ('total_phys','available_phys','total_page','available_page','total_virtual','available_virtual','extended')]
class ProcessMemory(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ('peak_working_set','working_set','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private_usage')]
kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
kernel.GlobalMemoryStatusEx.argtypes=[ctypes.POINTER(MemoryStatus)];kernel.GlobalMemoryStatusEx.restype=wintypes.BOOL
psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(ProcessMemory),wintypes.DWORD];psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
def available():
    v=MemoryStatus();v.length=ctypes.sizeof(v)
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(v)):raise ctypes.WinError(ctypes.get_last_error())
    return int(v.available_phys)
def working(p):
    v=ProcessMemory();v.cb=ctypes.sizeof(v)
    if not psapi.GetProcessMemoryInfo(int(p._handle),ctypes.byref(v),v.cb):
        if p.poll() is not None:return None
        raise ctypes.WinError(ctypes.get_last_error())
    return int(v.working_set)
def run_guarded(args,directory,cwd,env,deadline):
    d=Path(directory);target=d/'resource_guard.json'
    assert not target.exists() and not (d/'stdout.log').exists() and not (d/'stderr.log').exists()
    free=available();r=dict(status='not_launched',child_pid=None,args=list(map(str,args)),working_directory=str(cwd),TEMP=env['TEMP'],TMP=env['TMP'],returncode=None,actual_CLOSED=True,terminated_owned_child=False,maximum_working_set_bytes=2*1024**3,minimum_available_bytes=1024**3,sample_interval_seconds=.2,initial_available_bytes=free,minimum_observed_available_bytes=free,peak_working_set_bytes=0,samples=0)
    def save():target.write_text(json.dumps(r,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if free<1024**3 or time.monotonic()>=deadline:
        r['status']='not_launched_resource_or_child_deadline';save();return r
    start=time.monotonic();p=None
    try:
        with (d/'stdout.log').open('xb') as stdout,(d/'stderr.log').open('xb') as stderr:
            p=subprocess.Popen(list(map(str,args)),cwd=str(cwd),env=env,stdout=stdout,stderr=stderr)
            r.update(status='running',child_pid=p.pid,actual_CLOSED=False);save()
            while p.poll() is None:
                free=available();ws=working(p);r['samples']+=1;r['minimum_observed_available_bytes']=min(free,r['minimum_observed_available_bytes'])
                if ws is not None:r['peak_working_set_bytes']=max(ws,r['peak_working_set_bytes'])
                reason=('minimum_available_memory' if free<1024**3 else 'maximum_child_working_set' if ws is not None and ws>2*1024**3 else 'child_timeout' if time.monotonic()>=deadline else None)
                if reason:
                    r['termination_reason']=reason;p.terminate();r['terminated_owned_child']=True;break
                time.sleep(.2)
            p.wait(timeout=15)
    except BaseException as e:
        r['monitor_error']=type(e).__name__+': '+str(e)
        if p is not None and p.poll() is None:
            p.terminate();r['terminated_owned_child']=True
            try:p.wait(timeout=15)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=15)
    finally:
        r['returncode']=None if p is None else p.poll();r['actual_CLOSED']=p is None or p.poll() is not None;r['elapsed_seconds']=time.monotonic()-start
        r['status']='completed' if r['actual_CLOSED'] and r['returncode']==0 and not r['terminated_owned_child'] and 'monitor_error' not in r else 'failed_or_terminated';save()
    return r
