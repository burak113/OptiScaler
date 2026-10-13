"""Small Windows resource guard; no additional packages are installed."""
import os
import time
import psutil
import ctypes
from ctypes import wintypes


def prepare():
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000):
            raise ctypes.WinError(ctypes.get_last_error())
    for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_MAX_THREADS'):
        os.environ[name] = '2'
    os.environ['TEMP'] = os.environ['TMP'] = 'F:/FSRD/tmp'


def memory_guard():
    while psutil.virtual_memory().available < 1.5 * (1 << 30):
        print('Waiting for 1.5 GiB free RAM', flush=True)
        time.sleep(30)


def peak_bytes():
    # The provided psutil shim reports peak_wset=0. Read the Windows counter
    # directly instead of treating that unavailable value as a measurement.
    if os.name != 'nt':
        return int(psutil.Process().memory_info().peak_wset)
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
            'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    api = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
    api.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    api.restype = wintypes.BOOL
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    if not api(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(counters.PeakWorkingSetSize)
