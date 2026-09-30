"""Guard only a suspended child assigned to our Windows Job before it starts.

Job inheritance bounds the compiler/linker process tree. No unrelated process
is opened for termination; TerminateJobObject can touch only this owned job.
"""
from pathlib import Path
import ctypes,json,subprocess,time
from ctypes import wintypes as W
K=ctypes.WinDLL('kernel32',use_last_error=True);P=ctypes.WinDLL('psapi',use_last_error=True);N=ctypes.WinDLL('ntdll')
class MemoryStatus(ctypes.Structure):
    _fields_=[('length',W.DWORD),('load',W.DWORD)]+[(n,ctypes.c_uint64)for n in('total_phys','available_phys','total_page','available_page','total_virtual','available_virtual','extended')]
class PM(ctypes.Structure):
    _fields_=[('cb',W.DWORD),('faults',W.DWORD)]+[(n,ctypes.c_size_t)for n in('peak_working_set','working_set','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private_usage')]
class BasicLimits(ctypes.Structure):
    _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',W.DWORD),('minimum_ws',ctypes.c_size_t),('maximum_ws',ctypes.c_size_t),('active_limit',W.DWORD),('affinity',ctypes.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]
class IO(ctypes.Structure):_fields_=[(n,ctypes.c_uint64)for n in('readops','writeops','otherops','readbytes','writebytes','otherbytes')]
class Limits(ctypes.Structure):
    _fields_=[('basic',BasicLimits),('io',IO),('process_memory_limit',ctypes.c_size_t),('job_memory_limit',ctypes.c_size_t),('peak_process_memory',ctypes.c_size_t),('peak_job_memory',ctypes.c_size_t)]
K.CreateJobObjectW.argtypes=[ctypes.c_void_p,W.LPCWSTR];K.CreateJobObjectW.restype=W.HANDLE
K.SetInformationJobObject.argtypes=[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD];K.SetInformationJobObject.restype=W.BOOL
K.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE];K.AssignProcessToJobObject.restype=W.BOOL
K.QueryInformationJobObject.argtypes=[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD,ctypes.c_void_p];K.QueryInformationJobObject.restype=W.BOOL
K.TerminateJobObject.argtypes=[W.HANDLE,W.UINT];K.TerminateJobObject.restype=W.BOOL
K.CloseHandle.argtypes=[W.HANDLE];K.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];K.OpenProcess.restype=W.HANDLE
K.GlobalMemoryStatusEx.argtypes=[ctypes.POINTER(MemoryStatus)];K.GlobalMemoryStatusEx.restype=W.BOOL
K.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)];K.QueryFullProcessImageNameW.restype=W.BOOL
P.GetProcessMemoryInfo.argtypes=[W.HANDLE,ctypes.POINTER(PM),W.DWORD];P.GetProcessMemoryInfo.restype=W.BOOL
N.NtResumeProcess.argtypes=[W.HANDLE];N.NtResumeProcess.restype=ctypes.c_long
def check(ok):
    if not ok:raise ctypes.WinError(ctypes.get_last_error())
def available():
    m=MemoryStatus();m.length=ctypes.sizeof(m);check(K.GlobalMemoryStatusEx(ctypes.byref(m)));return int(m.available_phys)
def job_processes(job):
    # 256 slots comfortably exceeds our single-project /m1 /MP-disabled tree.
    b=ctypes.create_string_buffer(8+256*ctypes.sizeof(ctypes.c_size_t));check(K.QueryInformationJobObject(job,3,b,len(b),None))
    n=ctypes.c_uint32.from_buffer(b,4).value;assert n<=256
    return list((ctypes.c_size_t*n).from_buffer(b,8))
def sample(job):
    records=[]
    for pid in job_processes(job):
        handle=K.OpenProcess(0x1000|0x0010,False,pid)
        if not handle:continue
        try:
            m=PM();m.cb=ctypes.sizeof(m);buf=ctypes.create_unicode_buffer(32768);length=W.DWORD(len(buf))
            name=buf.value if K.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(length))else'unknown'
            if P.GetProcessMemoryInfo(handle,ctypes.byref(m),m.cb):records.append({'pid':int(pid),'image':name,'working_set_bytes':int(m.working_set)})
        finally:K.CloseHandle(handle)
    return records
def run_guarded_build(args,folder,cwd,env,timeout=2700,maximum_tree_ws=6*1024**3,minimum_free=1024**3,interval=.5):
    folder=Path(folder);target=folder/'owned_build_job_guard.json';assert not target.exists()
    r={'schema':'owned-build-Windows-Job-guard-v1','args':args,'cwd':str(cwd),'timeout_seconds':timeout,'maximum_tree_working_set_bytes':maximum_tree_ws,
        'minimum_available_memory_bytes':minimum_free,'interval_seconds':interval,'status':'not_launched','child_pid':None,'returncode':None,'samples':0,
        'peak_tree_working_set_bytes':0,'maximum_simultaneous_cl_exe':0,'minimum_observed_available_bytes':available(),'terminated_owned_job':False,'termination_reason':None,'observed_owned_processes':{}}
    def save():target.write_text(json.dumps(r,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if r['minimum_observed_available_bytes']<minimum_free:r['status']='not_launched_low_available_memory';save();return r
    job=K.CreateJobObjectW(None,None);check(job);limits=Limits();limits.basic.flags=0x2000;check(K.SetInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits)))
    started=time.monotonic();process=None
    try:
        with(folder/'build.stdout.bin').open('xb')as stdout,(folder/'build.stderr.bin').open('xb')as stderr,(folder/'owned_tree_samples.jsonl').open('x',encoding='utf-8')as samples:
            process=subprocess.Popen(args,cwd=cwd,env=env,stdout=stdout,stderr=stderr,creationflags=0x00000004|0x08000000)
            # Only our known newly created suspended child is assigned.
            check(K.AssignProcessToJobObject(job,int(process._handle)));status=N.NtResumeProcess(int(process._handle));assert status==0,status
            r.update(status='running',child_pid=process.pid);save()
            while process.poll()is None:
                records=sample(job);free=available();elapsed=time.monotonic()-started;ws=sum(x['working_set_bytes']for x in records)
                cl=sum(Path(x['image']).name.lower()=='cl.exe'for x in records)
                r['samples']+=1;r['minimum_observed_available_bytes']=min(r['minimum_observed_available_bytes'],free);r['peak_tree_working_set_bytes']=max(r['peak_tree_working_set_bytes'],ws);r['maximum_simultaneous_cl_exe']=max(r['maximum_simultaneous_cl_exe'],cl)
                for x in records:r['observed_owned_processes'][str(x['pid'])]=x['image']
                samples.write(json.dumps({'elapsed_seconds':elapsed,'available_bytes':free,'tree_working_set_bytes':ws,'cl_exe_count':cl,'owned_job_processes':records})+'\n');samples.flush()
                if r['samples']%10==0:save()
                reason='multiple_cl_exe'if cl>1 else'low_available_memory'if free<minimum_free else'tree_working_set_limit'if ws>maximum_tree_ws else'timeout'if elapsed>timeout else None
                if reason:
                    check(K.TerminateJobObject(job,3));r.update(terminated_owned_job=True,termination_reason=reason);process.wait(timeout=30);break
                time.sleep(interval)
            r['returncode']=process.wait(timeout=30);r['status']='completed'if r['returncode']==0 and not r['terminated_owned_job']else'failed_or_terminated'
    except BaseException as e:
        r.update(status='guard_exception',guard_error=type(e).__name__+': '+str(e))
        if process is not None and process.poll()is None:
            # Assignment failure occurs while suspended; this handle belongs to
            # our child. Otherwise job termination contains only its descendants.
            K.TerminateJobObject(job,3);process.terminate();process.wait(timeout=30);r['terminated_owned_job']=True
        if process is not None:r['returncode']=process.poll()
        raise
    finally:
        r['elapsed_seconds']=time.monotonic()-started;save();K.CloseHandle(job)
    return r
