"""Bound only the child created here, using lightweight Windows memory queries."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import json, subprocess, time

class MemoryStatus(ctypes.Structure):
    _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
        (name, ctypes.c_uint64) for name in ('total_phys', 'available_phys', 'total_page',
                                           'available_page', 'total_virtual', 'available_virtual', 'extended')]

class ProcessMemory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ('peak_working_set', 'working_set', 'peak_paged',
            'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private_usage')]

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)
kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]
psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

def available_memory():
    info = MemoryStatus(); info.length = ctypes.sizeof(info)
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(info.available_phys), int(info.total_phys)

def working_set(process):
    info = ProcessMemory(); info.cb = ctypes.sizeof(info)
    if not psapi.GetProcessMemoryInfo(int(process._handle), ctypes.byref(info), info.cb):
        if process.poll() is not None:
            return None
        raise ctypes.WinError(ctypes.get_last_error())
    return int(info.working_set)

def run_guarded(args, directory, timeout=240, maximum_working_set=2*1024**3,
                minimum_available_memory=1024**3, interval=.2):
    directory = Path(directory)
    target = directory/'resource_guard.json'
    if target.exists():
        raise ValueError('Preserve prior resource guard result')
    free, total = available_memory()
    result = dict(schema='owned-child-native-lightweight-resource-guard-v1', args=list(map(str,args)),
        timeout_seconds=timeout, maximum_working_set_bytes=maximum_working_set,
        minimum_available_memory_bytes=minimum_available_memory, sample_interval_seconds=interval,
        total_physical_bytes=total, initial_available_bytes=free, minimum_observed_available_bytes=free,
        peak_observed_working_set_bytes=0, samples=0, status='not_launched', child_pid=None,
        returncode=None, terminated_owned_child=False, termination_reason=None)
    def save():
        target.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    if free < minimum_available_memory:
        result['status']='not_launched_low_available_memory'; save(); return result
    start = time.monotonic()
    with (directory/'stdout.log').open('wb') as stdout, (directory/'stderr.log').open('wb') as stderr:
        process = subprocess.Popen(args, stdout=stdout, stderr=stderr)
        result.update(status='running', child_pid=process.pid); save()
        try:
            while process.poll() is None:
                free, _ = available_memory(); memory = working_set(process)
                result['samples'] += 1
                result['minimum_observed_available_bytes'] = min(free, result['minimum_observed_available_bytes'])
                if memory is not None:
                    result['peak_observed_working_set_bytes'] = max(memory, result['peak_observed_working_set_bytes'])
                reason = ('minimum_available_memory' if free < minimum_available_memory else
                          'maximum_child_working_set' if memory is not None and memory > maximum_working_set else
                          'timeout' if time.monotonic()-start > timeout else None)
                if reason:
                    result['termination_reason'] = reason
                    process.terminate(); process.wait(timeout=15)
                    result['terminated_owned_child'] = True
                    break
                time.sleep(interval)
        except BaseException as error:
            result['monitor_error'] = type(error).__name__+': '+str(error)
            if process.poll() is None:
                process.terminate(); process.wait(timeout=15)
                result['terminated_owned_child'] = True
                result['termination_reason'] = 'monitor_exception'
            raise
        finally:
            result['returncode'] = process.poll()
            result['elapsed_seconds'] = time.monotonic()-start
            result['status'] = ('completed' if result['returncode']==0 and not result['terminated_owned_child'] else 'failed_or_terminated')
            save()
    return result
