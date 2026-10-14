"""Actual bootstrap policy/PrepareLogger with real spdlog file-sink throughput.

Config storage, executable predicate, logger setup and shutdown are extracted from
production. Config singleton, executable location and disabled NGX/debug surfaces
are adapters. Accepted messages, filtering and file writes use real spdlog1.15.1.
No GPU, game writes or game-FPS extrapolation.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
from test_fsrd_nrd_root_restore import function

CPP = r'''
#define SPDLOG_USE_STD_FORMAT
#define SPDLOG_WCHAR_FILENAMES
#define SPDLOG_WCHAR_TO_UTF8_SUPPORT
#define SPDLOG_ACTIVE_LEVEL 0
#include <windows.h>
#include <spdlog/spdlog.h>
#include <spdlog/async.h>
#include <spdlog/sinks/basic_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/sinks/callback_sink.h>
#include <spdlog/sinks/null_sink.h>
#include <algorithm>
#include <array>
#include <barrier>
#include <chrono>
#include <cctype>
#include <concepts>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <numeric>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
unsigned checks=0;
void need(bool value,const char* message){if(!value)throw std::runtime_error(message);++checks;}
__CUSTOM__
struct Config {
__FIELDS__
 static Config* Instance(){static Config value;return &value;}
};
constexpr int NVSDK_NGX_LOGGING_LEVEL_OFF=0,NVSDK_NGX_LOGGING_LEVEL_VERBOSE=2;
constexpr int NVSDK_NGX_LOGGING_LEVEL_ON=1,NVSDK_NGX_Feature_SuperSampling=1;
struct State {
 struct {void (*LoggingCallback)(const char*,int,int)=nullptr;int MinimumLoggingLevel=0;} NVNGX_Logger;
 static State& Instance(){static State value;return value;}
};
namespace Util {
std::filesystem::path executable=L"Cyberpunk2077.exe";unsigned pathReads=0;
std::filesystem::path ExePath(){++pathReads;return executable;}
}
namespace NrdBridge {
__EXECUTABLE_GATE__
}
// Disabled native debug-output surface only; the active file sink remains real.
namespace spdlog::sinks {using debug_sink_mt=null_sink_mt;}
bool InitializeConsole(){throw std::runtime_error("Disabled console adapter reached");}
__POLICY_STATE__
__POLICY__
__LOGGER__
__FLUSH__
__CLOSE__
struct FlushProbe final:spdlog::sinks::base_sink<std::mutex> {
 uint64_t accepted=0,flushes=0;
 void sink_it_(const spdlog::details::log_msg&) override{++accepted;}
 void flush_() override{++flushes;}
};
struct ThrowingFlush final:spdlog::sinks::base_sink<std::mutex> {
 void sink_it_(const spdlog::details::log_msg&) override{}
 void flush_() override{throw std::runtime_error("deliberate one-shot flush error");}
};
uint64_t lines(const std::filesystem::path& path){std::ifstream f(path);std::string s;uint64_t n=0;while(std::getline(f,s))++n;return n;}
double percentile(std::vector<double> values,double fraction){std::sort(values.begin(),values.end());return values[size_t(fraction*double(values.size()-1))];}
void destination(const std::filesystem::path& path){auto* c=Config::Instance();c->LogToFile=true;c->LogFileName=path.wstring();}

void policyCase(const std::string& scenario,const std::filesystem::path& out){
 auto* c=Config::Instance();int level=0;bool expected=false,explicitLevel=false;
 bool bridge=true;signed levelValue=-1;
 if(scenario=="auto")expected=true;
 else if(scenario=="auto_case"){expected=true;Util::executable=L"CYBERPUNK2077.EXE";}
 else if(scenario=="runtime_off"){expected=true;c->FfxDenoiserNrdBridgeEnabled=false;}
 else if(scenario=="bridge_off")bridge=false;
 else if(scenario=="other_exe")Util::executable=L"AnotherGame.exe";
 else if(scenario=="suffix_exe")Util::executable=L"Cyberpunk2077.exe.bak";
 else if(scenario.starts_with("explicit_")){levelValue=std::stoi(scenario.substr(9));explicitLevel=true;level=levelValue;}
 else throw std::runtime_error("Unknown policy case");
 c->FfxDenoiserNrdBridge=bridge;
 if(explicitLevel)c->LogLevel.set_from_config(std::optional<int>(levelValue));
 need(c->LogLevel.has_value()==explicitLevel,"Actual optional distinguishes explicit level, including TRACE0");
 need(!c->LogAsync.value_or_default(),"Original synchronous LogAsync default retained");
 need(PrepareNrdBridgeAutomaticLogPolicy()==expected,"Automatic bridge policy is selected only for eligible auto");
 need(PrepareNrdBridgeAutomaticLogPolicy()==expected,"Bootstrap policy is idempotent");
 need(c->LogLevel.value_or_default()==(expected?2:level),"Exact explicit/default level preserved or automatic INFO selected");
 need(c->LogLevel.value_for_config_ignore_default().has_value()==explicitLevel,"Automatic choice remains volatile and explicit TRACE keeps its origin");
 if(explicitLevel)need(c->LogLevel.value_for_config_ignore_default().value()==levelValue,"Explicit selected value is unchanged");
 else need(!c->LogLevel.value_for_config().has_value(),"Automatic logger level does not persist to INI");
 if(!bridge||explicitLevel)need(Util::pathReads==0,"OFF or explicit selection avoids executable lookup");
 else need(Util::pathReads==1,"Real canonical executable predicate reads location once");
 const auto path=out/(scenario+".log");destination(path);PrepareLogger();
 auto logger=spdlog::default_logger();
 need(logger&&logger->level()==(expected?spdlog::level::info:spdlog::level::level_enum(level)),"Actual PrepareLogger uses selected level");
 need(logger->flush_level()==(expected?spdlog::level::warn:spdlog::level::trace),"Actual PrepareLogger keeps legacy flush or automatic WARN threshold");
 need(logger->sinks().size()==2&&std::dynamic_pointer_cast<spdlog::sinks::basic_file_sink_mt>(logger->sinks()[0]),"Production file sink is actual spdlog basic_file_sink_mt");
 auto probe=std::make_shared<FlushProbe>();logger->sinks().push_back(probe);
 uint64_t accepted=0,flushes=0;
 for(int i=0;i<6;++i){
  logger->log(spdlog::level::level_enum(i),"actual logger policy {} level {} address {:X}",scenario,i,uint64_t(0x123456780ULL));
  if(i>=(expected?2:level)){++accepted;if(i>=(expected?3:0))++flushes;}
  need(probe->accepted==accepted,"Filtering forwards exactly accepted levels");
  need(probe->flushes==flushes,"Actual spdlog flushes exactly at configured threshold");
 }
 logger->info("one-shot gameplay perf diagnostic {}",123);
 if((expected?2:level)<=2){++accepted;if(!expected)++flushes;}
 need(probe->accepted==accepted&&probe->flushes==flushes,"One-shot INFO respects normal filtering and automatic buffering");
 FlushLogger();need(probe->flushes==flushes+1,"Explicit perf flush calls actual spdlog flush exactly once");
 logger->sinks().push_back(std::make_shared<ThrowingFlush>());
 logger->set_error_handler([](const std::string&){throw std::runtime_error("deliberate flush handler error");});
 FlushLogger();need(probe->flushes==flushes+2,"One-shot flush swallows real spdlog sink/handler exceptions");
 logger->sinks().pop_back();
 CloseLogger();need(probe->flushes==flushes+3,"Production shutdown flushes once more");
 need(lines(path)==accepted,"Every accepted real file message survives shutdown exactly once");
 FlushLogger();need(probe->flushes==flushes+3,"One-shot flush is safe after default logger shutdown");
 std::cout<<"PASS policy="<<scenario<<" checks="<<checks<<" accepted="<<accepted<<" flushes="<<probe->flushes<<"\n";
}

void benchmark(const std::string& profile,unsigned count,const std::filesystem::path& out){
 auto* c=Config::Instance();c->FfxDenoiserNrdBridge=true;
 const bool automatic=profile=="filtered_hot"||profile=="buffered_info";
 const bool infoWork=profile=="legacy_info"||profile=="buffered_info";
 if(!automatic)c->LogLevel.set_from_config(std::optional<int>(infoWork?2:0));
 need(PrepareNrdBridgeAutomaticLogPolicy()==automatic,"Benchmark executes actual baseline/automatic policy");
 const auto path=out/(profile+"_"+std::to_string(count)+".log");destination(path);PrepareLogger();
 auto logger=spdlog::default_logger();
 need(logger->flush_level()==(automatic?spdlog::level::warn:spdlog::level::trace),"Benchmark uses actual production flush selection");
 constexpr unsigned threads=16,warmup=4,samples=20,total=warmup+samples;
 std::barrier start(threads+1),finish(threads+1);std::vector<std::thread> workers;
 for(unsigned t=0;t<threads;++t)workers.emplace_back([&,t]{
  for(unsigned round=0;round<total;++round){start.arrive_and_wait();
   for(unsigned n=t;n<count;n+=threads){
    const auto severity=infoWork?spdlog::level::info:(n%12<5?spdlog::level::trace:spdlog::level::debug);
    logger->log(severity,"HookToHeap Heap: {:X}, Heap type: {}, Cpu: {}-{}, Gpu: {}-{}, Desc count: {}",
        uint64_t(0x123456789ABCULL)+n,1,uint64_t(0x81000000ULL)+n,uint64_t(0x81040000ULL)+n,
        uint64_t(0x82000000ULL)+n,uint64_t(0x82040000ULL)+n,100002);
   }finish.arrive_and_wait();
  }
 });
 std::vector<double> elapsed;elapsed.reserve(samples);
 for(unsigned round=0;round<total;++round){auto a=std::chrono::steady_clock::now();start.arrive_and_wait();finish.arrive_and_wait();
  const double us=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-a).count();
  if(round>=warmup)elapsed.push_back(us);
 }
 for(auto& worker:workers)worker.join();
 auto a=std::chrono::steady_clock::now();CloseLogger();
 const double closeUs=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-a).count();
 const auto actualLines=lines(path);const uint64_t expected=automatic&&!infoWork?0:uint64_t(total)*count;
 need(actualLines==expected,"Exact native file line count; filtered path writes zero hot messages");
 const double mean=std::accumulate(elapsed.begin(),elapsed.end(),0.0)/elapsed.size();
 std::cout<<"{\"profile\":\""<<profile<<"\",\"threads\":"<<threads<<",\"messages_per_interval\":"<<count
  <<",\"warmup\":"<<warmup<<",\"samples\":"<<samples<<",\"mean_us\":"<<mean<<",\"p50_us\":"<<percentile(elapsed,.5)
  <<",\"p95_us\":"<<percentile(elapsed,.95)<<",\"p99_us\":"<<percentile(elapsed,.99)<<",\"max_us\":"<<*std::max_element(elapsed.begin(),elapsed.end())
  <<",\"close_flush_us\":"<<closeUs<<",\"native_file_lines\":"<<actualLines<<",\"bytes\":"<<std::filesystem::file_size(path)
  <<",\"checks\":"<<checks<<",\"samples_us\":[";
 for(size_t i=0;i<elapsed.size();++i){if(i)std::cout<<",";std::cout<<elapsed[i];}std::cout<<"]}\n";
}
int main(int argc,char** argv){try{
 need(argc>=4,"Native fixture arguments present");std::filesystem::path out=argv[3];std::filesystem::create_directories(out);
 if(std::string(argv[1])=="policy")policyCase(argv[2],out);
 else {need(argc==5,"Benchmark count argument present");benchmark(argv[2],unsigned(std::stoul(argv[4])),out);}
 return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<"\n";return 1;}}
'''


def run():
    logger=(ROOT/'OptiScaler/Logger.cpp').read_text()
    config=(ROOT/'OptiScaler/Config.h').read_text()
    bridge=(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp').read_text()
    fields=[]
    for name in ('LogLevel','LogToFile','LogToConsole','LogToNGX','LogToDebug','OpenConsole',
                 'LogFileName','LogAsync','LogAsyncThreads','FfxDenoiserNrdBridge','FfxDenoiserNrdBridgeEnabled'):
        matches=re.findall(r'^\s*(CustomOptional<[^;\n]+>\s+'+name+r'\s*\{[^\n;]*\};)',config,re.M)
        assert len(matches)==1,name
        fields.append(matches[0])
    custom=config[config.index('enum HasDefaultValue'):config.index('constexpr inline int UnboundKey')]
    body=CPP.replace('__CUSTOM__',custom).replace('__FIELDS__','\n'.join(fields))
    for marker,source,signature in (
        ('__POLICY__',logger,'bool PrepareNrdBridgeAutomaticLogPolicy() noexcept'),
        ('__LOGGER__',logger,'void PrepareLogger()'),('__CLOSE__',logger,'void CloseLogger()'),
        ('__FLUSH__',logger,'void FlushLogger() noexcept'),
        ('__EXECUTABLE_GATE__',bridge,'bool SupportedExecutable() noexcept')):
        body=body.replace(marker,function(source,signature))
    state=re.findall(r'^static bool gNrdBridgeAutomaticLogPolicy\s*=\s*false;',logger,re.M)
    assert len(state)==1
    body=body.replace('__POLICY_STATE__',state[0])
    # Exercise current production setup, not a handwritten formatting/flush replica.
    assert 'shared_logger->flush_on(gNrdBridgeAutomaticLogPolicy ? spdlog::level::warn : spdlog::level::trace);' in logger
    assert 'shared_logger->set_level((spdlog::level::level_enum) Config::Instance()->LogLevel.value_or_default());' in logger
    assert '#define SPDLOG_VER_PATCH 1' in (ROOT/'external/spdlog/include/spdlog/version.h').read_text()
    assert '#define SPDLOG_USE_STD_FORMAT' in (ROOT/'OptiScaler/SysUtils.h').read_text()
    assert (ROOT/'external/spdlog/include/spdlog/sinks/basic_file_sink.h').is_file()
    out=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT',os.environ.get('FSRD_TEST_OUTPUT_DIR','F:/FSRD/sol_batch/13d-menu/tests/logger-policy')))
    out.mkdir(parents=True,exist_ok=True)
    source=out/'nrd_logger_policy.cpp';source.write_text(body)
    executable=out/'nrd_logger_policy.exe'
    # Keep source execution encoding explicit; std::format matches production.
    # compile_cpp bypasses its cache for an explicit CL override; restore caller state.
    previous_cl=os.environ.get('CL')
    os.environ['CL']=(previous_cl+' ' if previous_cl else '')+'/utf-8'
    try:compile_cpp(source,executable,include_dirs=[ROOT/'external/spdlog/include'])
    finally:
        if previous_cl is None:os.environ.pop('CL',None)
        else:os.environ['CL']=previous_cl
    cases=['auto','auto_case','runtime_off','bridge_off','other_exe','suffix_exe',
           *['explicit_'+str(value) for value in (0,1,2,3,4,5,6)]]
    total=0;logs=[]
    for scenario in cases:
        result=subprocess.run([str(executable),'policy',scenario,str(out/'files')],capture_output=True,text=True)
        logs.append(dict(case=scenario,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
        (out/'policy-results.json').write_text(json.dumps(logs,indent=2)+'\n')
        if result.returncode:raise RuntimeError('Policy '+scenario+': '+result.stderr)
        total+=int(re.search(r'checks=(\d+)',result.stdout)[1])
    rows=[]
    for count in (500,1000,2000):
        for profile in ('legacy_hot','filtered_hot','legacy_info','buffered_info'):
            result=subprocess.run([str(executable),'benchmark',profile,str(out/'files'),str(count)],capture_output=True,text=True)
            if result.returncode:
                (out/'benchmark-failure.json').write_text(json.dumps(dict(profile=profile,count=count,stdout=result.stdout,stderr=result.stderr),indent=2))
                raise RuntimeError('Benchmark '+profile+': '+result.stderr)
            row=json.loads(result.stdout);rows.append(row);total+=row['checks']
            (out/'throughput.json').write_text(json.dumps(rows,indent=2)+'\n')
            print(profile,count,'mean_us='+str(row['mean_us']),'p95_us='+str(row['p95_us']),'lines='+str(row['native_file_lines']))
    output=dict(native_checks=total,policy_fresh_processes=len(cases),benchmark_rows=len(rows),threads=16,
                python_contract_categories=5,spdlog='1.15.1',format_backend='production SPDLOG_USE_STD_FORMAT',scope='actual production bootstrap/gate/CustomOptional/PrepareLogger/CloseLogger; real spdlog basic_file_sink_mt/full pattern; disabled NGX/debug/console adapters; no game FPS or disk durability claim')
    (out/'result.json').write_text(json.dumps(output,indent=2)+'\n')
    print('PASS:',total,'native logger checks;',len(rows),'real spdlog throughput rows')


if __name__=='__main__':run()
