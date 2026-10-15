"""Full production StagePerf host proof. Run under the serialized lead GPU lock.

--prepare-only generates source and never calls a compiler or a native process.
Original E2E fixture files and their 44/64/material cases are unchanged.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(HERE), str(HERE.parent)]
from fsrd_toolchain import compile_cpp
import test_fsrd_nrd_e2e as original
from test_fsrd_nrd_bridge_rr import bounded_run, DLL


def prepare(out):
    out.mkdir(parents=True, exist_ok=True)
    calls = []
    old_compile = original.compile_cpp
    original.compile_cpp = lambda *args, **kwargs: calls.append((args, kwargs))
    try:
        original.build(out)
    finally:
        original.compile_cpp = old_compile
    assert len(calls) == 1
    args, kwargs = calls[0]
    source = Path(args[0]).read_text(encoding='utf-8')
    support_path = out / 'stubs/fixture_support.h'
    support = support_path.read_text(encoding='utf-8')
    logger = r'''
#include <string_view>
#include <tuple>
#include <type_traits>
void StageFixtureLog(std::string_view,std::string_view) noexcept;
void StageFixtureFlush() noexcept;
template<class... A>void StageFixtureInfo(const char* format,A&&... values) noexcept {
 if constexpr(sizeof...(A)==1){auto tuple=std::forward_as_tuple(values...);
  if constexpr(std::is_convertible_v<decltype(std::get<0>(tuple)),std::string_view>)
   if(std::string_view(format).starts_with("[NRD_BRIDGE] stages "))StageFixtureLog(format,std::string_view(std::get<0>(tuple)));}
}
#define LOG_INFO(...) StageFixtureInfo(__VA_ARGS__)
'''
    assert support.count('#define LOG_INFO(...) ((void)0)') == 1
    support_path.write_text(support.replace('#define LOG_INFO(...) ((void)0)', logger), encoding='utf-8')
    (out / 'stubs/Logger.h').write_text('#pragma once\nvoid StageFixtureFlush() noexcept;\ninline void FlushLogger() noexcept {StageFixtureFlush();}\n', encoding='utf-8')
    # Include Perf before macro-counting StagePerf so only the latter's clock
    # calls are observed. Actual StagePerf source is compiled without rewriting.
    prefix = '''#define NOMINMAX
#include <Windows.h>
#include <atomic>
#include "''' + (ROOT / 'OptiScaler/misc/NrdBridgePerf_Dx12.h').as_posix() + '''"
BOOL WINAPI StageCountedCounter(LARGE_INTEGER*);
BOOL WINAPI StageCountedFrequency(LARGE_INTEGER*);
#define QueryPerformanceCounter StageCountedCounter
#define QueryPerformanceFrequency StageCountedFrequency
#include "''' + (ROOT / 'OptiScaler/misc/NrdBridgeStagePerf_Dx12.h').as_posix() + '''"
#undef QueryPerformanceCounter
#undef QueryPerformanceFrequency
#define main PreservedNrdE2EMain
'''
    appended = (HERE / 'fsrd_nrd_stage_perf_e2e.cpp').read_text(encoding='utf-8')
    final = prefix + source + '\n#undef main\n' + appended
    path, exe = out / 'stage_perf_e2e.cpp', out / 'stage_perf_e2e.exe'
    path.write_text(final, encoding='utf-8')
    args = (path, exe, *args[2:])
    return path, exe, args, kwargs


def validate(value):
    assert value['debug_errors'] == value['debug_warnings'] == 0
    assert value['accepted'] == 100 and value['stages_log_calls'] == value['stages_flush_calls'] == 1
    assert value['real_successful_outputs'] == 107 and value['unique_successful_outputs'] == 106
    assert value['provider_dispatches'] == 109
    assert value['callback_outside_mutex_injection_physical'] and value['callback_title_bindings_restored']
    assert value['stage_qpc_calls'] > 0 and value['stage_frequency_calls'] == 1
    text = value['stage_line']
    assert text.startswith('[NRD_BRIDGE] stages frames=100 SL_frame=1000..1101 ')
    assert 'window=first100_successful_unique_Consumer_output_recordings' in text
    assert 'scope=CPU_elapsed_not_GPU_or_display_FPS' in text
    assert 'time_valid=1' in text and 'overlapping_spans_do_not_sum=1' in text
    stages = re.findall(r'(\w+)\{samples=(\d+),events=(\d+),mean_ms=([\d.]+),max_ms=([\d.]+),p95_ms=([\d.]+),invalid=(\d+),saturated=(\d+)\}', text)
    assert len(stages) == 14
    for name, count, events, mean, maximum, p95, invalid, saturated in stages:
        assert int(count) == 100 and int(events) >= 100
        assert int(invalid) == int(saturated) == 0
        assert 0 <= float(mean) <= float(maximum) and 0 <= float(p95) <= float(maximum)
    frames = value['frames']
    assert len(frames) == 103
    assert [x['accepted'] for x in frames] == [min(100, i + 3) for i in range(103)]
    assert all(x['reported'] == int(i >= 97) for i, x in enumerate(frames))
    assert len({x['stage_qpc_calls'] for x in frames[97:]}) == 1
    return 15 + len(stages) * 3


def run():
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15e-quality/stage-perf-e2e'))
    path, exe, args, kwargs = prepare(out)
    if '--prepare-only' in sys.argv:
        print(json.dumps(dict(source=str(path), compiler_executed=False, gpu_executed=False)))
        return
    compile_cpp(*args, **kwargs)
    text, peak, elapsed, log = bounded_run([str(exe), str(out), str(DLL)], out / 'native_run')
    value = json.loads((out / 'stage-perf-e2e-result.json').read_text(encoding='utf-8'))
    value.update(python_checks=validate(value), native_log=str(log), elapsed_seconds=elapsed, peak_resident_bytes=peak,
                 dll_sha256=hashlib.sha256(DLL.read_bytes()).hexdigest(), fixture_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (out / 'stage-perf-e2e-result.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    run()
