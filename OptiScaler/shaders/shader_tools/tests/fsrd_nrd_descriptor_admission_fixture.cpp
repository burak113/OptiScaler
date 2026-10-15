// Actual production admission header. Fake native/mirror writes expose the two
// submission races deterministically; this is CPU synchronization, not GPU proof.
#define NOMINMAX
#include <windows.h>
#include <atomic>
#include <array>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <new>
#include <stdexcept>
#include <thread>
#include <vector>
BOOL WINAPI ObserveWait(volatile VOID*,PVOID,SIZE_T,DWORD);
#define WaitOnAddress ObserveWait
#include "__ROOT__/OptiScaler/misc/NrdBridgeDescriptorAdmission_Dx12.h"
#undef WaitOnAddress
namespace Admission=NrdBridgeDescriptorAdmission;
std::atomic<unsigned> gateWaits{0},writerWaits{0},failures{0},checks{0};
std::atomic<bool> denyAlloc{false},pauseSpy{false},spyEntered{false},releaseSpy{false};
void* operator new(size_t size){if(denyAlloc.load())throw std::bad_alloc();if(auto p=std::malloc(size?size:1))return p;throw std::bad_alloc();}
void operator delete(void* p)noexcept{std::free(p);}
void operator delete(void* p,size_t)noexcept{std::free(p);}
BOOL WINAPI ObserveWait(volatile VOID* address,PVOID compare,SIZE_T bytes,DWORD timeout){
    if(address==&Admission::Detail::gate.value)++gateWaits;else ++writerWaits;
    if(pauseSpy.exchange(false)){
        spyEntered=true;
        while(!releaseSpy.load())SwitchToThread();
    }
    return ::WaitOnAddress(address,compare,bytes,timeout);
}
void check(bool value,const char* message){++checks;if(!value)throw std::runtime_error(message);}
void observe(bool value){++checks;if(!value)++failures;}
template<class Predicate> void until(Predicate ready){
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
    while(!ready()){if(std::chrono::steady_clock::now()>deadline)throw std::runtime_error("bounded synchronization deadline");SwitchToThread();}
}
unsigned activeWriters(){unsigned result=0;for(auto& entry:Admission::Detail::writers)result+=entry.value.load();return result;}
struct Event{
    HANDLE value=CreateEventW(nullptr,TRUE,FALSE,nullptr);
    ~Event(){CloseHandle(value);}
    void set(){SetEvent(value);}
    void wait(){if(WaitForSingleObject(value,5000)!=WAIT_OBJECT_0)std::terminate();}
};
void nestingAndOff(){
    check(Admission::Healthy(),"initial healthy");
    denyAlloc=true;
    for(unsigned i=0;i<10000;++i){Admission::Mutation writer(false);Admission::Submission submit(false);observe(writer.Acquired()&&submit.Acquired());}
    denyAlloc=false;
    check(activeWriters()==0&&Admission::Detail::gate.value==0,"startup-off has no protocol writes");
    {Admission::Mutation outer(true);check(outer.Acquired()&&activeWriters()==1,"outer writer");
     {Admission::Mutation inner(true);check(inner.Acquired()&&activeWriters()==1,"nested writer counted once");}
     check(activeWriters()==1,"inner release retains outer writer");}
    check(activeWriters()==0,"writer exit drains");
    {Admission::Submission outer(true);check(outer.Acquired()&&Admission::SubmissionHeldByCurrentThread(),"outer submission TLS");
     {Admission::Submission inner(true);check(inner.Acquired()&&Admission::Detail::gate.value==1,"nested submission");}
     check(Admission::Detail::gate.value==1,"inner exit retains closed gate");}
    check(!Admission::SubmissionHeldByCurrentThread()&&Admission::Detail::gate.value==0,"outer opens gate");
}
void drainBeforeExecute(){
    Event nativeWritten,publishAllowed;
    std::atomic<unsigned> native{0},mirror{0};std::atomic<bool> executed{false};
    std::thread writer([&]{Admission::Mutation mutation(true);observe(mutation.Acquired());native=1;nativeWritten.set();publishAllowed.wait();mirror=1;});
    nativeWritten.wait();const auto before=writerWaits.load();
    std::thread submitter([&]{Admission::Submission submit(true);observe(submit.Acquired());observe(native.load()==mirror.load());executed=true;});
    until([&]{return writerWaits.load()>before;});
    check(!executed.load()&&native==1&&mirror==0,"pre-existing native write must publish before Execute");
    publishAllowed.set();writer.join();submitter.join();
    check(executed&&mirror==1,"submission proceeds after publication");
}
void holdThroughExecute(){
    Event executeEntered,finishExecute;
    std::atomic<unsigned> native{0};std::atomic<bool> finishedWriter{false};
    std::thread submitter([&]{Admission::Submission submit(true);observe(submit.Acquired());executeEntered.set();finishExecute.wait();observe(native==0);});
    executeEntered.wait();const auto before=gateWaits.load();
    std::thread writer([&]{Admission::Mutation mutation(true);observe(mutation.Acquired());++native;finishedWriter=true;});
    until([&]{return gateWaits.load()>before;});
    check(native==0&&!finishedWriter,"new native descriptor write waits through original Execute");
    finishExecute.set();submitter.join();writer.join();
    check(native==1&&finishedWriter,"writer proceeds after Execute returns");
}
void concurrent(unsigned count){
    struct alignas(64) Pair{std::atomic<unsigned> native{0},mirror{0};};
    std::array<Pair,16> pairs;std::atomic<bool> go{false};std::atomic<unsigned> finished{0};
    std::vector<std::thread> threads;threads.reserve(count);
    for(unsigned index=0;index<count;++index)threads.emplace_back([&,index]{
        until([&]{return go.load();});
        for(unsigned iteration=1;iteration<=12000;++iteration){
            Admission::Mutation write(true);observe(write.Acquired());
            pairs[index].native=iteration;
            if((iteration&255)==0)SwitchToThread();
            pairs[index].mirror=iteration;
        }++finished;
    });
    go=true;unsigned submissions=0;
    do{
        {Admission::Submission submit(true);check(submit.Acquired(),"parallel submission admitted");
         for(unsigned index=0;index<count;++index)check(pairs[index].native==pairs[index].mirror,"coherent native/mirror snapshot");}
        ++submissions;SwitchToThread();
    }while(finished.load()!=count||submissions<1000);
    for(auto& thread:threads)thread.join();
    for(unsigned index=0;index<count;++index)check(pairs[index].mirror==12000,"all parallel mutations complete");
    check(activeWriters()==0&&Admission::Healthy(),"parallel protocol fully released");
    std::cout<<"parallel writers="<<count<<" mutations="<<count*12000<<" coherent_submissions="<<submissions<<'\n';
}
void overhead(unsigned count){
    constexpr unsigned iterations=100000;
    std::atomic<bool> go{false};std::vector<std::thread> threads;threads.reserve(count);
    std::array<double,16> costs{};
    for(unsigned index=0;index<count;++index)threads.emplace_back([&,index]{
        until([&]{return go.load();});const auto begin=std::chrono::steady_clock::now();
        for(unsigned iteration=0;iteration<iterations;++iteration){Admission::Mutation writer(true);if(!writer.Acquired())++failures;}
        costs[index]=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-begin).count()/iterations;
    });
    go=true;for(auto& thread:threads)thread.join();
    double total=0,maximum=0;for(unsigned i=0;i<count;++i){total+=costs[i];maximum=(std::max)(maximum,costs[i]);}
    std::cout<<"guard_only writers="<<count<<" average_us="<<total/count<<" slowest_thread_average_us="<<maximum<<" (no native API or metadata)\n";
}
int main(int argc,char** argv)try{
    const std::string mode=argc>1?argv[1]:"normal";
    if(mode=="submit-in-mutation"){
        {Admission::Mutation writer(true);Admission::Submission submit(true);check(!submit.Acquired()&&!Admission::Healthy(),"reentrant submit fails closed");}
        check(activeWriters()==0&&Admission::Detail::gate.value==0,"reentrant submit releases writer");
    }else if(mode=="mutation-in-submit"){
        {Admission::Submission submit(true);Admission::Mutation writer(true);check(!writer.Acquired()&&!submit.Acquired()&&!Admission::Healthy(),"reentrant mutation fails closed");}
        check(activeWriters()==0&&Admission::Detail::gate.value==0,"reentrant mutation releases gate");
    }else if(mode=="failure-before-wait"){
        std::atomic<bool> rejected{false};Admission::Submission submit(true);pauseSpy=true;
        std::thread writer([&]{Admission::Mutation mutation(true);rejected=!mutation.Acquired();});
        until([]{return spyEntered.load();});Admission::Detail::Violation();releaseSpy=true;
        writer.join();check(rejected&&!Admission::Healthy(),"failure before native wait cannot hang");
    }else{
        nestingAndOff();drainBeforeExecute();holdThroughExecute();concurrent(8);concurrent(16);overhead(8);overhead(16);
        denyAlloc=true;for(unsigned i=0;i<10000;++i){Admission::Mutation writer(true);observe(writer.Acquired());}denyAlloc=false;
        check(activeWriters()==0&&Admission::Healthy(),"warm writer uses no C++ allocation");
    }
    check(failures==0,"all worker assertions");std::cout<<"PASS mode="<<mode<<" checks="<<checks.load()<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
