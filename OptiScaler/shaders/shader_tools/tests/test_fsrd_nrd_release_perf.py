"""Game-scale CPU timings of actual ResTrack Release/index/PSO cleanup bodies.

IUnknown objects, FrameSurvey and lease callbacks are explicit adapters; actual
ResTrack code, descriptor locking and participant cleanup execute without GPU
work. Timing is reported, while complexity/correctness assertions are exact.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
from test_fsrd_nrd_root_restore import function
import test_fsrd_nrd_release as lifetime

ROOT = lifetime.ROOT

CPP = r'''
using J=nlohmann::json;
constexpr bool indexed=__INDEXED__;
struct Data {
 size_t count;std::unique_ptr<Probe[]> resources,heaps,psos,lists;
 std::vector<std::shared_ptr<HeapInfo>> infos;
 explicit Data(size_t size):count(size),resources(new Probe[size]),heaps(new Probe[size]),psos(new Probe[size]),lists(new Probe[size]) {
  fgHeaps.reserve(size);gFreeHeapSlots.reserve(size);infos.reserve(size);
  for(size_t i=0;i<size;++i){
   resources[i].expectClean=heaps[i].expectClean=psos[i].expectClean=lists[i].expectClean=false;
   auto* resource=reinterpret_cast<ID3D12Resource*>(&resources[i]);
   auto* heap=reinterpret_cast<ID3D12DescriptorHeap*>(&heaps[i]);
   auto* pso=reinterpret_cast<ID3D12PipelineState*>(&psos[i]);
   auto* list=reinterpret_cast<ID3D12GraphicsCommandList*>(&lists[i]);
   auto info=std::make_shared<HeapInfo>();info->heap=heap;info->cpuStart=0x100000+i*64;info->cpuEnd=info->cpuStart+32;
   info->gpuStart=0x10000000+i*64;info->gpuEnd=info->gpuStart+32;info->version=i+1;
   info->info=std::make_shared<HeapInfo::Info[]>(1);info->info[0].buffer=resource;info->occupiedSlots.insert(0);
   __REGISTER__
   infos.push_back(info);_trackedResources[resource]={{info,info->version.load(),0}};
   gRRResourceStates.insert(resource);gRRResourceActivity.insert(resource);SeedFixtureRRCache(resource);
   heapMetadata.insert(heap);heapMetadata.insert(resource);heapMetadata.insert(pso);heapMetadata.insert(list);
   __PREPARE_PSO__
   {std::scoped_lock lock(gRRPsoMutex);RecordRRPsoProducer(resource,pso,false);}
   auto& state=gRRCommandListPsoStates[list];auto old=RRPsoPointers(state);
   state.currentPso=state.lastGraphicsPso=state.lastComputePso=pso;UpdateRRPsoListReferencesLocked(list,old,state);
  }
 }
};
J measure(const char* name,size_t samples,const std::function<void(size_t)>& run){
 std::vector<double> micros;micros.reserve(samples);const auto scans=poolRangeBegins,reads=poolIndexedReads,rrScans=rrRangeBegins;
 for(size_t i=0;i<samples;++i){const auto start=std::chrono::steady_clock::now();run(i);const auto end=std::chrono::steady_clock::now();micros.push_back(std::chrono::duration<double,std::micro>(end-start).count());}
 const auto globalScans=poolRangeBegins-scans,heapReads=poolIndexedReads-reads,psoScans=rrRangeBegins-rrScans;
 std::sort(micros.begin(),micros.end());double sum=0;for(auto value:micros)sum+=value;
 return {{"name",name},{"samples",samples},{"mean_us",sum/samples},{"p50_us",micros[samples/2]},
 {"p95_us",micros[size_t(samples*.95)]},{"p99_us",micros[size_t(samples*.99)]},{"max_us",micros.back()},
 {"full_heap_range_begins",globalScans},{"heap_slot_reads",heapReads},{"full_producer_or_list_range_begins",psoScans}};
}
void noGlobalScan(const J& row,size_t maximumHeapReads){if(!indexed)return;need(row["full_heap_range_begins"]==0&&row["full_producer_or_list_range_begins"]==0,"release/PSO cleanup never begins a global heap/resource/list traversal");need(row["heap_slot_reads"].get<size_t>()<=maximumHeapReads,"heap address cleanup touches only its directly indexed participant");}
void resetData(){clearHeaps();FrameSurvey::metadataHealthy=true;gRRResourceStates.clear();gRRResourceActivity.clear();gRRTrackedResources.clear();__CLEAR_RESOURCE_SIZES__gRRResourcePsoProducers.clear();gRRPsoMetadata.clear();gRRCommandListPsoStates.clear();__CLEAR_REVERSE__}
J gameScale(size_t count){
 resetData();Data data(count);const size_t samples=1000;J rows=J::array();
 gNrdBridgeWrappers=gNrdBridgeDeviceWrappers=gSurveyWrappers=true;gHeapReleaseSharesResource=true;gSharedResourceReleaseObserver=&hkRelease;
 for(size_t i=0;i<samples;++i)data.resources[i].refs=2;
 rows.push_back(measure("resource_nonfinal",samples,[&](size_t i){hkRelease(reinterpret_cast<ID3D12Resource*>(&data.resources[i]));}));noGlobalScan(rows.back(),0);
 for(size_t i=0;i<samples;++i)need(data.resources[i].refs==1&&!data.resources[i].destroyed&&data.infos[i]->info[0].buffer==reinterpret_cast<ID3D12Resource*>(&data.resources[i]),"nonfinal resource preserves live descriptor and metadata participant");
 rows.push_back(measure("resource_final",samples,[&](size_t i){hkRelease(reinterpret_cast<ID3D12Resource*>(&data.resources[i]));}));noGlobalScan(rows.back(),0);
 for(size_t i=0;i<samples;++i){auto* resource=reinterpret_cast<ID3D12Resource*>(&data.resources[i]);need(data.resources[i].destroyed&&data.resources[i].refs==0&&!_trackedResources.contains(resource)&&!gRRResourcePsoProducers.contains(resource)&&!heapMetadataLive(resource)&&!data.infos[i]->info[0].buffer,"final resource removes actual descriptor/state/producer/metadata participants before final release");}
 const size_t offset=count-samples;
 for(size_t i=0;i<samples;++i)data.heaps[offset+i].refs=2;
 rows.push_back(measure("heap_shared_nonfinal",samples,[&](size_t i){hkHeapRelease(reinterpret_cast<ID3D12DescriptorHeap*>(&data.heaps[offset+i]));}));noGlobalScan(rows.back(),0);
 for(size_t i=0;i<samples;++i)need(data.heaps[offset+i].refs==1&&!data.heaps[offset+i].destroyed&&data.infos[offset+i]->active,"nonfinal shared heap retains its descriptor registry");
 rows.push_back(measure("heap_shared_final",samples,[&](size_t i){hkHeapRelease(reinterpret_cast<ID3D12DescriptorHeap*>(&data.heaps[offset+i]));}));noGlobalScan(rows.back(),samples*2);
 for(size_t i=0;i<samples;++i){auto* heap=reinterpret_cast<ID3D12DescriptorHeap*>(&data.heaps[offset+i]);need(data.heaps[offset+i].destroyed&&!data.infos[offset+i]->active&&!data.infos[offset+i]->info&&!heapMetadataLive(heap),"final shared heap removes actual FG/native-descriptor participants");}
 rows.push_back(measure("pso_final",samples,[&](size_t i){hkPsoRelease(reinterpret_cast<ID3D12PipelineState*>(&data.psos[offset+i]));}));noGlobalScan(rows.back(),0);
 for(size_t i=0;i<samples;++i){auto* pso=reinterpret_cast<ID3D12PipelineState*>(&data.psos[offset+i]);auto* list=reinterpret_cast<ID3D12GraphicsCommandList*>(&data.lists[offset+i]);auto* resource=reinterpret_cast<ID3D12Resource*>(&data.resources[offset+i]);auto& state=gRRCommandListPsoStates.at(list);need(data.psos[offset+i].destroyed&&!gRRPsoMetadata.contains(pso)&&!gRRResourcePsoProducers.at(resource).contains(pso)&&!state.currentPso&&!state.lastGraphicsPso&&!state.lastComputePso,"final PSO cleans its real producer and all three list-pointer roles");}
 if(indexed){__INDEX_TESTS__}
 auto result=J{{"live_resource_setup",count},{"live_heap_setup",count},{"live_producer_setup",count},{"live_list_setup",count},{"descriptor_lock_stripes",HeapInfo::DESCRIPTOR_LOCK_STRIPE_COUNT},{"rows",rows}};
 resetData();return result;
}
int main()try{
 SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
 __MUTATION_TESTS__
 J rows=J::array();for(size_t size:{size_t(2000),size_t(100000)})rows.push_back(gameScale(size));
 PROCESS_MEMORY_COUNTERS memory{};GetProcessMemoryInfo(GetCurrentProcess(),&memory,sizeof(memory));need(memory.PeakWorkingSetSize<2500ull*1024*1024,"CPU fixture remains within 2.5GB process budget");
 std::cout<<J{{"indexed",indexed},{"checks",checks},{"datasets",rows},{"peak_working_set_bytes",memory.PeakWorkingSetSize},{"scope","actual extracted ResTrack Release/heap-index/PSO-participant cleanup, 256 descriptor lock stripes and real affected descriptor/producer/list metadata; IUnknown, FrameSurvey, lease and PSO installer seams are CPU adapters; no GPU work or timing pass thresholds"}}.dump(2)<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


def run():
    out=Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True,exist_ok=True)
    baseline='--baseline' in sys.argv
    if baseline:
        original=Path('F:/FSRD/sol_batch/12f-audit/heap_release_perf_baseline3251')
        os.environ['FSRD_RELEASE_RESOURCE_SOURCE']=str(original/'ResTrack_dx12.cpp')
        os.environ['FSRD_RELEASE_RESOURCE_HEADER']=str(original/'ResTrack_dx12.h')
    os.environ['FSRD_RELEASE_GENERATE_ONLY']='1'
    generated=lifetime.run()
    cpp=generated.read_text()
    source=Path(os.environ.get('FSRD_RELEASE_RESOURCE_SOURCE',ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp')).read_text()
    header=Path(os.environ.get('FSRD_RELEASE_RESOURCE_HEADER',ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.h')).read_text()
    indexed='static bool RegisterTrackedHeapLocked(' in source
    occupied='std::unordered_set<UINT> occupiedSlots;' in header
    cpp=cpp[:cpp.index('int main(int argc,char** argv)')]
    cpp=cpp.replace('#include <map>','#include <map>\n#include <limits>\n#include <psapi.h>\n#include <json.hpp>')
    counters=r'''
size_t poolRangeBegins=0,poolIndexedReads=0,rrRangeBegins=0;
template<class Key,class Value>struct CountedMap:std::unordered_map<Key,Value>{using Base=std::unordered_map<Key,Value>;auto begin(){++rrRangeBegins;return Base::begin();}auto begin()const{++rrRangeBegins;return Base::begin();}};
struct CountedHeapPool:std::vector<std::shared_ptr<HeapInfo>>{using Base=std::vector<std::shared_ptr<HeapInfo>>;auto begin(){++poolRangeBegins;return Base::begin();}auto begin()const{++poolRangeBegins;return Base::begin();}auto& operator[](size_t slot){++poolIndexedReads;return Base::operator[](slot);}const auto& operator[](size_t slot)const{++poolIndexedReads;return Base::operator[](slot);}};
'''
    cpp=cpp.replace('std::vector<std::shared_ptr<HeapInfo>> fgHeaps;',counters+'\nCountedHeapPool fgHeaps;')
    cpp=cpp.replace('static constexpr size_t DESCRIPTOR_LOCK_STRIPE_COUNT=2;','static constexpr size_t DESCRIPTOR_LOCK_STRIPE_COUNT=256;')
    cpp=cpp.replace('std::array<std::shared_mutex,DESCRIPTOR_LOCK_STRIPE_COUNT> descriptorLocks;','mutable std::array<std::shared_mutex,DESCRIPTOR_LOCK_STRIPE_COUNT> descriptorLocks;')
    cpp=cpp.replace('struct HeapSlot { void ClearSlotIfMatches(size_t,ID3D12Resource*) { ++slotsCleaned; } };','struct HeapInfo;using HeapSlot=HeapInfo;')
    cpp=cpp.replace('struct HeapInfo {','struct HeapInfo : std::enable_shared_from_this<HeapInfo> {')
    cpp=cpp.replace('struct TrackedResourceSlot { std::weak_ptr<HeapSlot> heap; size_t index=0; uint64_t heapVersion=0; };','struct TrackedResourceSlot { std::weak_ptr<HeapSlot> heap; uint64_t heapVersion=0; UINT index=0; };')
    cpp=cpp.replace('std::weak_ptr<HeapSlot>{},0,info->version.load()','std::weak_ptr<HeapSlot>{},info->version.load(),0')
    if occupied and 'std::mutex occupiedSlotsMutex;' not in cpp:
        cpp=cpp.replace('UINT numDescriptors=1;','UINT numDescriptors=1;std::mutex occupiedSlotsMutex;std::unordered_set<UINT> occupiedSlots;')
    # Use the actual ResourceInfo shape, including the trailing exact birth token.
    hud=(ROOT/'OptiScaler/hudfix/Hudfix_Dx12.h').read_text()
    resource_type=function(hud,'enum ResourceType')+';'
    resource_info=function(hud,'typedef struct ResourceInfo')+' resource_info;'
    shape=resource_type+'\n'+resource_info+r'''
template<class T>struct CountedInfoArray{
 std::shared_ptr<T[]> value;mutable size_t reads=0;
 CountedInfoArray()=default;explicit CountedInfoArray(T* data):value(data){}CountedInfoArray& operator=(std::shared_ptr<T[]> data){value=std::move(data);return *this;}
 T& operator[](size_t index){++reads;return value[index];}const T& operator[](size_t index)const{++reads;return value[index];}
 explicit operator bool()const{return bool(value);}void reset(){value.reset();}
};
'''
    cpp=cpp.replace('struct HeapInfo : std::enable_shared_from_this<HeapInfo> {',shape+'\nstruct HeapInfo : std::enable_shared_from_this<HeapInfo> {')
    cpp=cpp.replace('struct Info {ID3D12Resource* buffer=nullptr;uint64_t lastUsedFrame=0;};std::shared_ptr<Info[]> info;','using Info=ResourceInfo;CountedInfoArray<Info> info;')
    clear_slot=lifetime.function_with_defaults(header,'void ClearSlotIfMatches(UINT index, ID3D12Resource* resource',
                                               body_prefix='\n ++slotsCleaned;')
    position=cpp.index('bool DeactivateAndClear()')
    if occupied:
        methods='\n'.join(function(header,s) for s in (
            'bool GetCpuIndex(', 'bool GetGpuIndex(', 'void DetachFromOldResourceLocked(', 'void AttachToNewResourceLocked(',
            'void SetByCpuHandle(', 'void SetByGpuHandle(', 'void ClearByCpuHandle(', 'void ClearByGpuHandle(', 'void ClearSlotLocked('))
        methods='HeapInfo()=default;\n'+function(header,'HeapInfo(ID3D12DescriptorHeap* heap, SIZE_T cpuStart')+'\n'+methods
        cpp=cpp[:position]+methods+'\n'+cpp[position:]
        cpp=cpp.replace('#define LOG_ERROR(...) ((void)0)','#define LOG_ERROR(...) ((void)0)\n#define LOG_TRACK(...) ((void)0)')
        cpp=cpp.replace('UINT numDescriptors=1;','UINT numDescriptors=1,increment=32,type=0;')
    position=cpp.index('bool GetCpuIndex(') if occupied else cpp.index('bool DeactivateAndClear()')
    cpp=cpp[:position]+clear_slot+'\nstd::shared_mutex& GetDescriptorLock(UINT index) const{return descriptorLocks[index&(DESCRIPTOR_LOCK_STRIPE_COUNT-1)];}\n'+cpp[position:]
    cpp=cpp.replace(',gRRResourcePsoProducers;',';')
    cpp=cpp.replace(',gRRPsoMutex;',';')
    cpp=cpp.replace('void CleanupRRResourcePsoProducersLocked(ID3D12Resource* resource) {gRRResourcePsoProducers.erase(resource);}','')
    rr=source[source.index('enum class RRPsoKind'):source.index('static uint64_t HashRRBytes(')]
    rr=rr.replace('static std::unordered_map<ID3D12GraphicsCommandList*, RRCommandListPsoState>','static CountedMap<ID3D12GraphicsCommandList*, RRCommandListPsoState>')
    rr=rr.replace('static std::unordered_map<ID3D12Resource*,\n','static CountedMap<ID3D12Resource*,\n')
    # Counter type is needed before the RR declarations, independently of pool type.
    start=cpp.index('template<class Key,class Value>struct CountedMap:')
    end=cpp.index('\nstruct CountedHeapPool:',start)
    map_counter=cpp[start:end]
    cpp=cpp[:start]+cpp[end:]
    cpp=cpp.replace('void CleanupRRPsoReferences(void*) { ++psoCleaned; }','\nextern size_t rrRangeBegins;\n'+map_counter+'\n'+rr)
    cleanup=function(source,'static void CleanupRRPsoReferences(void* object)').replace('CleanupRRPsoReferences','ActualCleanupRRPsoReferences',1)
    strong_pso='static bool PublishRRPsoMetadata(' in source
    rr_extra='\nstd::atomic<uint64_t> gRRResourceInspectorFrame=0;\nvoid CleanupRRPsoReferences(void*);\n'
    if strong_pso:
        rr_extra+='static bool RRInspectorBirthsEnabled() noexcept;\n'
        rr_extra+=r'''
// Native coverage is a CPU seam; real prepared publication and weak paths follow unchanged.
unsigned psoCreatorCoverageCalls=0,psoCreatorUnderBirth=0;
bool EnsurePsoReleaseHook(ID3D12PipelineState*){++psoCreatorCoverageCalls;if(NrdBridgeBirth::InMetadataScope())++psoCreatorUnderBirth;return true;}
'''
        rr_extra+='\n'.join(function(source,s) for s in (
            'template <class T> static NrdBridgeBirth::Token RRStrongReceiver(',
            'static RRPsoMetadata& EnsureRRPsoMetadata(', 'static RRPsoMetadata* FindRRPsoMetadataLocked(',
            'static bool PublishRRPsoMetadata(', 'static RRCommandListPsoState& RRPsoListStateLocked(',
            'static bool RRPsoListAvailable(', 'static void RecordRRPsoProducer('))
    else:
        rr_extra+='void EnsurePsoReleaseHook(ID3D12PipelineState*){}\n'
        rr_extra+='\n'.join(function(source,s) for s in ('static RRPsoMetadata& EnsureRRPsoMetadata(','static void RecordRRPsoProducer('))
    if not indexed:
        rr_extra+='\nstatic std::array<ID3D12PipelineState*,3> RRPsoPointers(const RRCommandListPsoState& state){return {state.currentPso,state.lastGraphicsPso,state.lastComputePso};}\nvoid UpdateRRPsoListReferencesLocked(ID3D12GraphicsCommandList*,const std::array<ID3D12PipelineState*,3>&,RRCommandListPsoState&){}\n'
    rr_extra+=cleanup+'\nvoid CleanupRRPsoReferences(void* object){++psoCleaned;ActualCleanupRRPsoReferences(object);}\n'
    position=cpp.index('// Registry scaffolding is an adapter;')
    cpp=cpp[:position]+rr_extra+cpp[position:]
    if indexed:
        cpp=cpp.replace('static void HookResource(ID3D12Device*);','static void HookResource(ID3D12Device*);\n static void hkSetPipelineState(ID3D12GraphicsCommandList*,ID3D12PipelineState*);\n static HRESULT hkReset(ID3D12GraphicsCommandList*,ID3D12CommandAllocator*,ID3D12PipelineState*);')
        close=function(source,'HRESULT ResTrack_Dx12::hkClose(ID3D12GraphicsCommandList* This)')
        close_tail=close[close.index('    if (gRRResourceInspectorEnabled.load'):]
        adapters=r'''
std::atomic<bool> gRRResourceInspectorEnabled=true;
struct MenuOverlayDx{static ID3D12GraphicsCommandList* MenuCommandList(){return nullptr;}};
unsigned pipelineOriginalCalls=0,resetOriginalCalls=0,closeOriginalCalls=0,resetLeaseDetachCalls=0,resetFenceCalls=0;
HRESULT resetResult=S_OK;
void originalPipeline(ID3D12GraphicsCommandList*,ID3D12PipelineState*){++pipelineOriginalCalls;}
HRESULT originalReset(ID3D12GraphicsCommandList*,ID3D12CommandAllocator*,ID3D12PipelineState*){++resetOriginalCalls;return resetResult;}
HRESULT originalClose(ID3D12GraphicsCommandList*){++closeOriginalCalls;return S_OK;}
auto o_SetPipelineState=&originalPipeline;auto o_Reset=&originalReset;auto o_Close=&originalClose;
std::mutex gRRMarkerMutex;std::unordered_set<ID3D12GraphicsCommandList*> gRRCommandListMarkers;
namespace RecordedComputeLease{int Capture(ID3D12GraphicsCommandList*){return 1;}void Detach(int){++resetLeaseDetachCalls;}}
namespace RRTraceFence{void ResetSucceeded(ID3D12GraphicsCommandList*){++resetFenceCalls;}}
'''
        if 'static RRPreparedRecording PrepareRRRecording(' in source:
            # This fixture verifies PSO participants and Release, not optional inspector state proof.
            adapters+=r'''
struct RRPreparedRecording {};
RRPreparedRecording PrepareRRRecording(ID3D12GraphicsCommandList*){return {};}
void RRRecordingSucceeded(const RRPreparedRecording&,ID3D12GraphicsCommandList*){}
'''
        if 'static void ForgetOwnedRRList(' in source:
            adapters+='\n'+function(source,'static void ForgetOwnedRRList(')
        adapters+='\n'+function(source,'void ResTrack_Dx12::hkSetPipelineState(')+'\n'+function(source,'HRESULT ResTrack_Dx12::hkReset(')
        close_prefix='const auto inspectorRecording=PrepareRRRecording(This);\n' if 'RRRecordingSucceeded(inspectorRecording,This)' in close_tail else ''
        adapters+='\n// Exact RR-inspector tail of legacy Close; preceding FG work is outside this CPU seam.\nHRESULT rrCloseTail(ID3D12GraphicsCommandList* This){\n'+close_prefix+close_tail
        cpp+=adapters+r'''
void mutationTests(){
 auto* list=reinterpret_cast<ID3D12GraphicsCommandList*>(uintptr_t(0x4000));
 auto* a=reinterpret_cast<ID3D12PipelineState*>(uintptr_t(0x5000));auto* b=reinterpret_cast<ID3D12PipelineState*>(uintptr_t(0x6000));auto* c=reinterpret_cast<ID3D12PipelineState*>(uintptr_t(0x7000));
 auto* resource=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x8000));
 ResTrack_Dx12::hkSetPipelineState(list,a);need(pipelineOriginalCalls==1&&gRRPsoCommandLists.at(a).contains(list),"actual pipeline setter indexes participant and calls original once");
 auto& state=gRRCommandListPsoStates.at(list);auto previous=RRPsoPointers(state);state.lastGraphicsPso=a;state.lastComputePso=b;UpdateRRPsoListReferencesLocked(list,previous,state);EnsureRRPsoMetadata(b);
 ResTrack_Dx12::hkSetPipelineState(list,c);need(gRRPsoCommandLists.at(a).size()==1&&gRRPsoCommandLists.at(b).size()==1&&gRRPsoCommandLists.at(c).size()==1,"pipeline replacement retains distinct last-graphics/last-compute participants without duplicate list refs");
 RecordRRPsoProducer(resource,a,false);CleanupRRPsoReferences(a);need(!state.lastGraphicsPso&&state.currentPso==c&&state.lastComputePso==b&&!gRRPsoCommandLists.contains(a)&&!gRRPsoProducerResources.contains(a)&&!gRRResourcePsoProducers.at(resource).contains(a),"dying PSO clears only its producer and exact list fields");
 resetResult=E_FAIL;need(FAILED(ResTrack_Dx12::hkReset(list,nullptr,a))&&resetOriginalCalls==1&&state.currentPso==c&&state.lastComputePso==b&&resetLeaseDetachCalls==0&&resetFenceCalls==0,"failed actual Reset keeps all prior participants and original result");
 resetResult=S_OK;need(SUCCEEDED(ResTrack_Dx12::hkReset(list,nullptr,b))&&resetOriginalCalls==2&&resetLeaseDetachCalls==1&&resetFenceCalls==1&&!gRRPsoCommandLists.contains(c)&&gRRPsoCommandLists.at(b).size()==1&&state.currentPso==b&&!state.lastComputePso&&!state.lastGraphicsPso,"successful actual Reset replaces all three roles and retains one initial-PSO membership");
 need(rrCloseTail(list)==S_OK&&closeOriginalCalls==1&&!gRRCommandListPsoStates.contains(list)&&!gRRPsoCommandLists.contains(b),"exact legacy Close inspector tail removes participant membership and calls original once");
 ResTrack_Dx12::hkSetPipelineState(list,c);gRRPsoMetadata.erase(c);CleanupRRPsoReferences(c);need(!gRRCommandListPsoStates.at(list).currentPso&&!gRRPsoCommandLists.contains(c),"participant index prevents dying pointer resurrection even if optional metadata allocation had failed");
 ResTrack_Dx12::hkSetPipelineState(list,b);RecordRRPsoProducer(resource,b,false);{std::scoped_lock lock(gRRPsoMutex);CleanupRRResourcePsoProducersLocked(resource);}need(!gRRResourcePsoProducers.contains(resource)&&!gRRPsoProducerResources.contains(b),"resource release removes its reverse producer participant without touching other resources");
 CleanupRRPsoReferences(list);need(!gRRCommandListPsoStates.contains(list)&&!gRRPsoCommandLists.contains(b),"shared raw-address final list cleanup removes membership before stale PSO can re-register");
 gRRResourcePsoProducers.clear();gRRPsoMetadata.clear();gRRCommandListPsoStates.clear();gRRPsoProducerResources.clear();gRRPsoCommandLists.clear();
}
'''
        if strong_pso:
            cpp=cpp.replace('EnsureRRPsoMetadata(b);','need(PublishRRPsoMetadata(b),"explicit strong creator publishes last-compute PSO before weak output use");')
            cpp=cpp.replace(' ResTrack_Dx12::hkSetPipelineState(list,a);',r'''
 auto* unpublished=reinterpret_cast<ID3D12PipelineState*>(uintptr_t(0x9000));
 const auto beforeUnknown=psoCreatorCoverageCalls;RecordRRPsoProducer(resource,unpublished,false);
 need(!gRRResourcePsoProducers.contains(resource)&&psoCreatorCoverageCalls==beforeUnknown,"unknown weak producer fails closed without cold native coverage/publication");
 ResTrack_Dx12::hkSetPipelineState(list,a);''',1)
            cpp=cpp.replace(' RecordRRPsoProducer(resource,a,false);CleanupRRPsoReferences(a);',r'''
 const auto beforeWeak=psoCreatorCoverageCalls;{std::scoped_lock lock(gRRPsoMutex);RecordRRPsoProducer(resource,a,false);}
 need(psoCreatorCoverageCalls==beforeWeak&&psoCreatorUnderBirth==0,"prepared weak producer never calls native coverage while metadata is locked");CleanupRRPsoReferences(a);''',1)
    index_tests=r'''
 need(gHeapSlotsByAddress.size()==count-samples&&gHeapCpuRanges.size()==count-samples&&gHeapGpuRanges.size()==count-samples,"only released heaps leave address/CPU/GPU indexes");
 auto info=std::make_shared<HeapInfo>();info->heap=reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(0x1234));info->cpuStart=0x100000;info->cpuEnd=info->cpuStart+16;info->info=std::make_shared<HeapInfo::Info[]>(1);
 const auto slots=fgHeaps.size(),free=gFreeHeapSlots.size();{std::unique_lock lock(_heapRegistryMutex);need(!RegisterTrackedHeapLocked(info),"overlapping live CPU ranges are explicitly rejected");}
 info->cpuStart=0x100000+offset*64;info->cpuEnd=info->cpuStart+16;{std::unique_lock lock(_heapRegistryMutex);need(RegisterTrackedHeapLocked(info),"released native range/address is reusable without a pool search");}
 need(fgHeaps.size()==slots&&gFreeHeapSlots.size()==free-1&&FindTrackedHeapByAddress(info->heap)==info,"slot reuse has bounded lookup and no pool growth");
 {std::shared_lock lock(_heapRegistryMutex);need(FindIndexedHeapRangeLocked(gHeapCpuRanges,info->cpuStart,false)==info&&!FindIndexedHeapRangeLocked(gHeapCpuRanges,info->cpuEnd,false),"ordered range lookup uses exact half-open boundaries");}
 need(DeactivateTrackedHeap(info)&&!FindTrackedHeapByAddress(info->heap),"reused heap clears its exact index membership");
'''
    register='{std::unique_lock lock(_heapRegistryMutex);need(RegisterTrackedHeapLocked(info),"100k setup registers indexed live heap");}' if indexed else 'fgHeaps.push_back(info);'
    extra=CPP.replace('__INDEXED__','true' if indexed else 'false').replace('__REGISTER__',register)
    extra=extra.replace('__PREPARE_PSO__','need(PublishRRPsoMetadata(pso,RRPsoKind::Compute),"strong creator publishes PSO metadata before weak producer registration");' if strong_pso else '')
    extra=extra.replace('__CLEAR_RESOURCE_SIZES__','gRRResourceSizeIndex.clear();' if 'static void EraseRRTrackedResourceLocked(' in source else '')
    extra=extra.replace('__INDEX_TESTS__',index_tests if indexed else '').replace('__CLEAR_REVERSE__','gRRPsoProducerResources.clear();gRRPsoCommandLists.clear();' if indexed else '')
    extra=extra.replace('__MUTATION_TESTS__','mutationTests();' if indexed else '')
    if not occupied:
        extra=extra.replace('info->occupiedSlots.insert(0);','')
    cpp+=extra
    if '--sparse' in sys.argv:
        if not occupied:
            raise RuntimeError('Sparse fixture requires the populated-slot implementation.')
        cpp=cpp[:cpp.index('int main()try{')]+r'''
void sparseTests(){
 for(bool populated:{false,true}){
  auto heap=std::make_shared<HeapInfo>(nullptr,0x100000,0x100000+1000000*32ull,0x20000000,0x20000000+1000000*32ull,1000000,32,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  need(heap->info.reads==0&&!heap->info[999999].buffer,"actual million-slot constructor relies on ResourceInfo initialization and performs no extra whole-descriptor scan");
  heap->version=123;ResourceInfo resource{};resource.buffer=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x5000));
  if(populated){heap->SetByCpuHandle(heap->cpuStart+999999*32ull,resource);need(heap->occupiedSlots.size()==1&&_trackedResources.at(resource.buffer).size()==1&&_trackedResources.at(resource.buffer)[0].heapVersion==123&&_trackedResources.at(resource.buffer)[0].index==999999,"actual SetByCpuHandle indexes the one populated slot at the end of a million-slot heap");}
  const auto reads=heap->info.reads;const auto start=std::chrono::steady_clock::now();need(heap->DeactivateAndClear(),"sparse heap deactivation succeeds");const auto elapsed=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count();const auto touched=heap->info.reads-reads;
  need(touched==(populated?3u:0u),"million-slot deactivation reads exactly its zero/one real descriptor, never all empty slots");need(!heap->info&&heap->occupiedSlots.empty()&&!_trackedResources.contains(resource.buffer)&&!heap->active,"sparse final cleanup clears storage, occupancy and exact resource reverse reference");
  std::cout<<"SPARSE slots=1000000 populated="<<populated<<" descriptor_reads="<<touched<<" final_us="<<elapsed<<'\n';
 }
 auto heap=std::make_shared<HeapInfo>();heap->numDescriptors=1024;heap->cpuStart=0x100000;heap->cpuEnd=heap->cpuStart+32768;heap->gpuStart=0x20000000;heap->gpuEnd=heap->gpuStart+32768;heap->info=std::make_shared<HeapInfo::Info[]>(1024);heap->version=145;
 ResourceInfo a{},b{};a.buffer=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x5000));b.buffer=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x6000));
 heap->SetByCpuHandle(heap->cpuStart+3*32,a);heap->SetByGpuHandle(heap->gpuStart+3*32,b);need(!_trackedResources.contains(a.buffer)&&heap->occupiedSlots.size()==1&&_trackedResources.at(b.buffer).size()==1,"CPU/GPU descriptor replacement keeps one occupied slot and only its current resource reverse edge");
 heap->SetByCpuHandle(heap->cpuStart+3*32,b);need(heap->occupiedSlots.size()==1&&_trackedResources.at(b.buffer).size()==1,"same-resource descriptor metadata refresh creates no duplicate occupancy/reverse entry");
 heap->ClearByGpuHandle(heap->gpuStart+3*32);need(heap->occupiedSlots.empty()&&!_trackedResources.contains(b.buffer)&&!heap->info[3].buffer,"explicit GPU descriptor clear removes occupancy and reverse edge");
 heap->SetByCpuHandle(heap->cpuStart+4*32,a);{std::lock_guard lock(_trackedResourcesMutex);_trackedResources.erase(a.buffer);}heap->ClearSlotIfMatches(4,a.buffer);need(heap->occupiedSlots.empty()&&!heap->info[4].buffer,"resource-final descriptor cleanup removes occupancy after global reverse map was already detached");
 heap->SetByCpuHandle(heap->cpuStart+5*32,a);{std::lock_guard lock(_trackedResourcesMutex);_trackedResources.erase(a.buffer);}heap->SetByCpuHandle(heap->cpuStart+5*32,b);need(heap->occupiedSlots.size()==1&&_trackedResources.at(b.buffer).size()==1,"descriptor overwrite handles a previously detached resource reverse map without stale occupancy");
 heap->ClearByCpuHandle(heap->cpuStart+5*32);need(heap->occupiedSlots.empty()&&!_trackedResources.contains(b.buffer),"explicit CPU descriptor clear removes the last occupied slot");need(heap->DeactivateAndClear(),"cleared heap safely deactivates without scanning empty slots");
}
int main()try{SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);sparseTests();std::cout<<"PASS: "<<checks<<" sparse heap occupancy/actual mutation checks\n";return 0;}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''
    if not baseline:
        cpp=cpp.replace("int main()try{", "int main()try{NrdBridgePerf::Configure([](const NrdBridgePerf::Report&) noexcept {});NrdBridgePerf::ConsumerFrame(1);")
    target,exe=out/'nrd_release_perf.cpp',out/'nrd_release_perf.exe'
    target.write_text(cpp)
    if os.environ.get('FSRD_RELEASE_PERF_GENERATE_ONLY') == '1':
        return target
    compile_cpp(target,exe,('d3d12.lib','dxgi.lib','dxguid.lib','psapi.lib',str(ROOT/'OptiScaler/library/detours/detours.lib')),(ROOT/'OptiScaler',ROOT/'external/nlohmann'))
    result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=120)
    (out/'native.log').write_text(result.stdout+result.stderr)
    result.check_returncode()
    if '--sparse' in sys.argv:
        print(result.stdout,end='')
        (out/'result.json').write_text(json.dumps({'checks':int(re.search(r'PASS: (\d+)',result.stdout).group(1)),
            'scope':'actual HeapInfo Set/Clear/Attach/Detach/Deactivate bodies, actual ResourceInfo shape, million-slot heap zero/one true resource participant, counted descriptor reads and CPU-only IUnknown/metadata adapters','native_log':result.stdout})+'\n')
        return
    measured=json.loads(result.stdout)
    (out/'result.json').write_text(json.dumps(measured,indent=2)+'\n')
    print('PASS:',measured['checks'],'actual Release/participant correctness checks; baseline=',baseline)
    for dataset in measured['datasets']:
        for row in dataset['rows']:
            print(dataset['live_resource_setup'],row['name'],'mean_us=',round(row['mean_us'],4),'p99_us=',round(row['p99_us'],4),'global_heap_scans=',row['full_heap_range_begins'],'global_RR_scans=',row['full_producer_or_list_range_begins'])


if __name__=='__main__':
    run()
