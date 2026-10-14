"""Activated native-birth root/list protocol with production root hook bodies.

Preserves the restore-lock suite first. Byte-data COM ABI adapters implement
IUnknown/ID3D12Object; derived GPU methods remain explicit recording seams.
This is CPU proof, not a D3D runtime, physical detour, or GPU correctness claim.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_fsrd_nrd_restore_locks as base
from test_fsrd_nrd_root_restore import function

ROOT = base.ROOT

ADAPTER = r'''
bool birthCasesActive=false, failNextAllocation=false;
unsigned nativeUnderBirth=0,nativeUnderTracker=0,coverageCalls=0,healthCalls=0;
unsigned factoryCalls=0,notifyCalls=0,oomHits=0,originalCreateCalls=0,deserializerReleases=0;
void* operator new(size_t bytes){
 if(failNextAllocation){failNextAllocation=false;++oomHits;throw std::bad_alloc();}
 if(void* p=std::malloc(bytes?bytes:1))return p;throw std::bad_alloc();
}
void operator delete(void* p)noexcept{std::free(p);}
void operator delete(void* p,size_t)noexcept{std::free(p);}
void checkNativeContext(){
 if(!birthCasesActive)return;
 nativeUnderBirth+=NrdBridgeBirth::InMetadataScope();
 for(auto* mutex:{&rootStatesMutex,&descriptorHeapsMutex,&pipelineStatesMutex,&rootSignatureMutex,&rootSigParameterCountMutex}){
  if(mutex->try_lock())mutex->unlock();else ++nativeUnderTracker;
 }
}
struct RootEffects{std::array<NrdBridgeBirth::Token,64> retired;unsigned count=0;};
void* makeEffects()noexcept{checkNativeContext();++factoryCalls;try{return new RootEffects;}catch(...){return nullptr;}}
bool detachEffects(void* raw,const NrdBridgeBirth::Token& token)noexcept{
 auto& effects=*static_cast<RootEffects*>(raw);
 if(effects.count==effects.retired.size())return false;
 effects.retired[effects.count++]=token;
 D3D12Hooks::OnBridgeObjectReleased(token);return true;
}
void notifyEffects(void* raw)noexcept{checkNativeContext();++notifyCalls;delete static_cast<RootEffects*>(raw);}
namespace NrdBridgeNativeBirth{
 bool ObserveReleaseCoverage(IUnknown*)noexcept{checkNativeContext();++coverageCalls;return true;}
}
struct FakeObject:ID3D12Object{
 std::array<std::byte,16> stamp{},countTag{};bool hasStamp=false,hasCount=false;
 bool armCountWrite=false,armCountRead=false;
 ULONG references=1;unsigned adds=0,releases=0,reads=0,writes=0;
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out)override{
  checkNativeContext();if(!out)return E_POINTER;*out=nullptr;
  if(iid==__uuidof(IUnknown)||iid==__uuidof(ID3D12Object)||iid==__uuidof(ID3D12RootSignature)){
   *out=this;AddRef();return S_OK;
  }return E_NOINTERFACE;
 }
 ULONG STDMETHODCALLTYPE AddRef()override{checkNativeContext();++adds;return ++references;}
 ULONG STDMETHODCALLTYPE Release()override{checkNativeContext();++releases;return --references;}
 HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID guid,UINT* size,void* out)override{
  checkNativeContext();++reads;
  const bool instance=guid==NrdBridgeNativeBirth::InstanceGuid;
  if(!size)return E_POINTER;
  if(!(instance?hasStamp:hasCount))return DXGI_ERROR_NOT_FOUND;
  if(*size<16){*size=16;return DXGI_ERROR_MORE_DATA;}
  *size=16;std::memcpy(out,(instance?stamp:countTag).data(),16);
  if(!instance&&armCountRead){armCountRead=false;failNextAllocation=true;}
  return S_OK;
 }
 HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID guid,UINT size,const void* data)override{
  checkNativeContext();++writes;if(size!=16)return E_INVALIDARG;
  const bool instance=guid==NrdBridgeNativeBirth::InstanceGuid;
  std::memcpy((instance?stamp:countTag).data(),data,16);
  (instance?hasStamp:hasCount)=true;
  if(!instance&&armCountWrite){armCountWrite=false;failNextAllocation=true;}
  return S_OK;
 }
 HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID,const IUnknown*)override{return E_NOTIMPL;}
 HRESULT STDMETHODCALLTYPE SetName(LPCWSTR)override{return S_OK;}
 template<class T>T* as(){return reinterpret_cast<T*>(static_cast<ID3D12Object*>(this));}
 void reuse(){hasStamp=hasCount=false;stamp={};countTag={};}
};
struct AliasUnknown:IUnknown{
 FakeObject* root;ULONG refs=1;explicit AliasUnknown(FakeObject& object):root(&object){}
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out)override{
  checkNativeContext();if(iid==__uuidof(ID3D12RootSignature))return root->QueryInterface(iid,out);
  if(iid==__uuidof(IUnknown)){*out=this;AddRef();return S_OK;}*out=nullptr;return E_NOINTERFACE;
 }
 ULONG STDMETHODCALLTYPE AddRef()override{checkNativeContext();return ++refs;}
 ULONG STDMETHODCALLTYPE Release()override{checkNativeContext();return --refs;}
};
struct FakeDeserializer:ID3D12VersionedRootSignatureDeserializer{
 D3D12_VERSIONED_ROOT_SIGNATURE_DESC desc{};
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void** out)override{*out=this;return S_OK;}
 ULONG STDMETHODCALLTYPE AddRef()override{return 1;}
 ULONG STDMETHODCALLTYPE Release()override{checkNativeContext();++deserializerReleases;return 1;}
 HRESULT STDMETHODCALLTYPE GetRootSignatureDescAtVersion(D3D_ROOT_SIGNATURE_VERSION,const D3D12_VERSIONED_ROOT_SIGNATURE_DESC** out)override{*out=&desc;return S_OK;}
 const D3D12_VERSIONED_ROOT_SIGNATURE_DESC* STDMETHODCALLTYPE GetUnconvertedRootSignatureDesc()override{checkNativeContext();return &desc;}
} deserializer;
struct FakeBlob:ID3DBlob{
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void** out)override{*out=this;return S_OK;}
 ULONG STDMETHODCALLTYPE AddRef()override{return 1;}
 ULONG STDMETHODCALLTYPE Release()override{checkNativeContext();return 1;}
 LPVOID STDMETHODCALLTYPE GetBufferPointer()override{return this;}
 SIZE_T STDMETHODCALLTYPE GetBufferSize()override{return 1;}
} blob;
HRESULT deserializeResult=S_OK,serializeResult=S_OK,createResult=S_OK;
void* returnedRoot=nullptr;bool expectFreshCreate=false;
HRESULT WINAPI deserialize(LPCVOID,SIZE_T,REFIID,void** out){checkNativeContext();*out=SUCCEEDED(deserializeResult)?&deserializer:nullptr;return deserializeResult;}
HRESULT WINAPI serialize(const D3D12_VERSIONED_ROOT_SIGNATURE_DESC*,ID3DBlob** out,ID3DBlob** error){checkNativeContext();*out=SUCCEEDED(serializeResult)?&blob:nullptr;*error=nullptr;return serializeResult;}
HRESULT nativeCreate(ID3D12Device*,UINT,const void*,SIZE_T,REFIID,void** out){
 checkNativeContext();++originalCreateCalls;
 if(expectFreshCreate&&rootSigParameterCount.contains(static_cast<ID3D12RootSignature*>(returnedRoot)))throw std::runtime_error("root count published before successful native Create");
 *out=SUCCEEDED(createResult)?returnedRoot:nullptr;return createResult;
}
namespace D3d12Proxy{auto D3D12CreateVersionedRootSignatureDeserializer_(){return &deserialize;}}
auto o_CreateRootSignature=&nativeCreate;
auto o_D3D12SerializeVersionedRootSignature=&serialize;
template<class T>void ApplySamplerOverrides(T&){}
'''

CASES = r'''
void activateBirth(){
 birthCasesActive=true;gNrdBridgeDeviceWrappers=true;FrameSurvey::internalScope=false;isNrdBridgeInjection=false;
 Config::Instance()->RestoreComputeSignature.current=true;Config::Instance()->RestoreGraphicSignature.current=true;Config::Instance()->ExtendedStateRestore.current=true;
 need(NrdBridgeNativeBirth::ConfigureRetirement(makeEffects,detachEffects,notifyEffects),"actual native birth dispatcher activates for root hooks");
}
NrdBridgeBirth::Token retire(const NrdBridgeBirth::Token& token){
 NrdBridgeNativeBirth::RetirementScope effects;
 need(effects.Valid(),"retirement payload prepared outside every tracker lock");
 need(NrdBridgeBirth::RetireCurrentInstance(token),"same physical instance retirement succeeds");return token;
}
void createdRootCases(){
 std::array<FakeObject,7> objects;
 for(unsigned i=0;i<3;++i){
  auto& object=objects[i];returnedRoot=object.as<ID3D12RootSignature>();expectFreshCreate=true;
  deserializer.desc.Version=static_cast<D3D_ROOT_SIGNATURE_VERSION>(i+1);
  if(i==0)deserializer.desc.Desc_1_0.NumParameters=7;
  else if(i==1)deserializer.desc.Desc_1_1.NumParameters=7;
  else deserializer.desc.Desc_1_2.NumParameters=7;
  void* output=nullptr;auto nativeBefore=originalCreateCalls;auto releasesBefore=deserializerReleases;
  need(hkCreateRootSignature(nullptr,0,&object,1,__uuidof(ID3D12RootSignature),&output)==S_OK&&output==returnedRoot,"all root blob versions preserve successful native result/output");
  const auto born=NrdBridgeBirth::Capture(output);
  NativeRootParameterCount count;std::memcpy(&count,object.countTag.data(),sizeof(count));
  need(born&&born->CacheAdmissible()&&rootSigBirths.at(object.as<ID3D12RootSignature>())==born&&rootSigParameterCount.at(object.as<ID3D12RootSignature>())==7,"successful creator publishes count with the exact native root birth");
  need(count.count==7&&count.version==1&&count.instanceStamp==born->InstanceStamp()&&originalCreateCalls==nativeBefore+1&&deserializerReleases==releasesBefore+1,"scalar count stamp and native/deserializer calls remain exact");
  const auto writes=object.writes;PublishCreatedRootParameters(output,__uuidof(ID3D12RootSignature),7);
  need(NrdBridgeBirth::Capture(output)==born&&object.writes==writes+1,"interned creator keeps physical/logical identity and only rewrites identical count tag");
  retire(born);
 }
 expectFreshCreate=false;deserializer.desc.Version=D3D_ROOT_SIGNATURE_VERSION_1_0;deserializer.desc.Desc_1_0.NumParameters=7;
 Config::Instance()->MipmapBiasOverride=0.0f;
 for(unsigned i=3;i<5;++i){
  serializeResult=i==3?S_OK:E_FAIL;returnedRoot=objects[i].as<ID3D12RootSignature>();void* output=nullptr;
  const auto before=originalCreateCalls;
  need(hkCreateRootSignature(nullptr,0,&blob,1,__uuidof(ID3D12RootSignature),&output)==S_OK&&output==returnedRoot&&originalCreateCalls==before+1,"override success and serialization fallback each call native Create exactly once");
  need(rootSigParameterCount.at(static_cast<ID3D12RootSignature*>(output))==7,"override and fallback publish original parameter count after success");
  retire(NrdBridgeBirth::Capture(output));
 }
 Config::Instance()->MipmapBiasOverride.reset();serializeResult=S_OK;createResult=E_FAIL;returnedRoot=objects[5].as<ID3D12RootSignature>();void* output=returnedRoot;
 const auto before=originalCreateCalls;
 need(hkCreateRootSignature(nullptr,0,&blob,1,__uuidof(ID3D12RootSignature),&output)==E_FAIL&&output==nullptr&&originalCreateCalls==before+1,"failed native creator preserves HRESULT and null output exactly once");
 need(!rootSigParameterCount.contains(static_cast<ID3D12RootSignature*>(returnedRoot))&&!NrdBridgeBirth::Capture(returnedRoot),"failed creator publishes no root birth/count metadata");
 createResult=S_OK;AliasUnknown alias(objects[6]);returnedRoot=&alias;
 const auto refs=objects[6].references;const auto adds=objects[6].adds,releases=objects[6].releases;
 need(hkCreateRootSignature(nullptr,0,&blob,1,__uuidof(IUnknown),&output)==S_OK&&output==&alias,"arbitrary returned IID preserves original interface identity");
 const auto typed=objects[6].as<ID3D12RootSignature>();const auto born=NrdBridgeBirth::Capture(typed);const auto aliasBorn=NrdBridgeBirth::Capture(&alias);
 need(born&&aliasBorn&&born->InstanceStamp()==aliasBorn->InstanceStamp()&&rootSigParameterCount.at(typed)==7,"QI normalization registers proven output alias with the same physical stamp");
 need(objects[6].references==refs&&objects[6].adds==adds+1&&objects[6].releases==releases+1,"QI normalization owns only one temporary balanced title reference outside all locks");
 retire(born);retire(aliasBorn);
 need(NrdBridgeBirth::Healthy(),"all valid creator/version/fallback/IID paths preserve metadata health");
}
void bindingBirthCases(){
 FakeObject listObject,rootObject,heapObject,psoObject;
 watched=listObject.as<ID3D12GraphicsCommandList>();root=rootObject.as<ID3D12RootSignature>();heap=heapObject.as<ID3D12DescriptorHeap>();pipeline=psoObject.as<ID3D12PipelineState>();
 PublishCreatedRootParameters(root,__uuidof(ID3D12RootSignature),7);
 auto bind=[&]{
  hkSetComputeRootSignature(watched,root);hkSetDescriptorHeaps(watched,1,&heap);hkSetPipelineState(watched,pipeline);
  hkSetComputeRootDescriptorTable(watched,1,{101});hkSetComputeRootDescriptorTableLate(watched,5,{505});
  const uint32_t a[]={11,99,33,66},b[]={77,88};hkSetComputeRoot32BitConstants(watched,2,4,a,0);hkSetComputeRoot32BitConstantsLate(watched,2,2,b,5);
  hkSetComputeRootConstantBufferView(watched,3,0x8000);hkSetComputeRootShaderResourceView(watched,4,0x9000);hkSetComputeRootUnorderedAccessView(watched,6,0xa000);
 };
 bind();const auto listBirth=NrdBridgeBirth::Capture(watched),rootBirth=NrdBridgeBirth::Capture(root),heapBirth=NrdBridgeBirth::Capture(heap),psoBirth=NrdBridgeBirth::Capture(pipeline);
 const auto reads=listObject.reads+rootObject.reads+heapObject.reads+psoObject.reads,coverage=coverageCalls,factories=factoryCalls;
 FrameSurvey::ComputeBindings current;
 {NrdBridgeLifetime::ScopedBorrow borrow;
  need(borrow.Acquired()&&D3D12Hooks::GetComputeBindingsForBridge(watched,current)&&D3D12Hooks::CanRestoreRootSignature(watched),"exact-born title bindings admit weak CPU snapshot under actual physical borrow");
  need(current.receiverBirth==listBirth&&current.rootBirth==rootBirth&&current.heapBirths==std::vector<NrdBridgeBirth::Token>{heapBirth},"receiver/root/heaps snapshot carries exact current nodes in descriptor order");
  need(current.tables.size()==2&&current.views.size()==3&&current.pipelineBirth==nullptr,"snapshot retains every table/root-view and does not invent optional PSO birth");
  isNrdBridgeInjection=true;calls.clear();D3D12Hooks::RestoreRoot(watched);verifyBytes();isNrdBridgeInjection=false;
 }
 need(listObject.reads+rootObject.reads+heapObject.reads+psoObject.reads==reads&&coverageCalls==coverage&&factoryCalls==factories,"snapshot/preflight/native restore perform no private-data getter, installer, or retirement allocation");
 calls.clear();hkSetComputeRoot32BitConstant(watched,2,44,1);
 need(listObject.reads+rootObject.reads+heapObject.reads+psoObject.reads==reads&&coverageCalls==coverage&&factoryCalls==factories,"hot actual setter uses covered four-entry receiver cache without native identity work");
 retire(rootBirth);need(!rootSigParameterCount.contains(root)&&!D3D12Hooks::GetComputeBindingsForBridge(watched,current),"retired root node invalidates retained bound metadata and direct count row");
 const auto countReads=rootObject.reads;hkSetComputeRootSignature(watched,root);const auto rootReborn=NrdBridgeBirth::Capture(root);
 need(rootReborn&&rootReborn!=rootBirth&&rootReborn->InstanceStamp()==rootBirth->InstanceStamp()&&rootObject.reads==countReads+2,"logical reobservation reads native GUID and immutable scalar count outside tracker/Birth locks");
 need(rootSigBirths.at(root)==rootReborn&&rootStates.at(watched).rootBirth==rootReborn&&rootStates.at(watched).size()==7,"same physical root reinstates exact count and current root rows");
 bind();retire(heapBirth);need(!D3D12Hooks::GetComputeBindingsForBridge(watched,current)&&!D3D12Hooks::CanRestoreRootSignature(watched),"retired heap referent cannot admit a borrowed descriptor snapshot or native replay");
 bind();retire(psoBirth);need(!D3D12Hooks::CanRestoreRootSignature(watched),"retired PSO referent denies exact restore admission");bind();
 const auto old=NrdBridgeBirth::Capture(watched);
 {NrdBridgeBirth::ScopedRelease pending(old);
  listObject.reuse();calls.clear();hkSetComputeRootSignatureLate(watched,root);
  const auto fresh=NrdBridgeBirth::Capture(watched);
  need(fresh&&fresh->InstanceStamp()!=old->InstanceStamp()&&fresh!=old,"pending old Release forces native read and distinct recycled-list identity");
  need(rootStates.at(watched).receiverBirth==fresh&&rootStates.at(watched)[1].type==RootEntryType::Invalid&&!descriptorHeaps.contains(watched)&&!pipelineStates.contains(watched),"recycled list removes every prior receiver binding before new argument publication");
  D3D12Hooks::OnBridgeObjectReleased(old);
  need(rootStates.at(watched).receiverBirth==fresh&&bridgeComputeRoots.at(watched)==root,"delayed exact-token root cleanup cannot erase a new receiver at the same address");
  {NrdBridgeNativeBirth::RetirementScope effects;need(!NrdBridgeBirth::RetireCurrentInstance(old)&&NrdBridgeBirth::Capture(watched)==fresh,"old actual-zero ticket cannot retire a different native stamp");}
 }
 bind();const auto currentList=NrdBridgeBirth::Capture(watched);D3D12Hooks::OnBridgeCommandListReset(watched,pipeline);
 need(!rootStates.contains(watched)&&!descriptorHeaps.contains(watched)&&pipelineStates.at(watched).receiverBirth==currentList&&pipelineStates.at(watched).pipelineBirth==NrdBridgeBirth::Capture(pipeline),"successful live Reset preserves exact initial-PSO node and discards all root/heap rows");
 bind();retire(currentList);
 need(!rootStates.contains(watched)&&!signatures.contains(watched)&&!descriptorHeaps.contains(watched)&&!pipelineStates.contains(watched),"final current list retirement removes all direct caches without native access");
 retire(NrdBridgeBirth::Capture(root));retire(NrdBridgeBirth::Capture(heap));retire(NrdBridgeBirth::Capture(pipeline));
}
void unknownAndOffCases(){
 FakeObject listObject,unknownRoot;
 watched=listObject.as<ID3D12GraphicsCommandList>();root=unknownRoot.as<ID3D12RootSignature>();
 calls.clear();hkSetComputeRootSignature(watched,root);hkSetComputeRoot32BitConstant(watched,2,99,0);
 const auto node=NrdBridgeBirth::Capture(root);FrameSurvey::ComputeBindings current;
 need(node&&node->CacheAdmissible()&&NrdBridgeBirth::Healthy()&&!rootStates.at(watched).rootCountKnown&&rootStates.at(watched).size()==64,"prehook root missing count tag remains locally unknown with bounded legacy arguments and healthy identity");
 need(!D3D12Hooks::GetComputeBindingsForBridge(watched,current)&&!D3D12Hooks::CanRestoreRootSignature(watched),"unknown root count never admits a bridge snapshot or injection");
 const auto warnings=warningCalls;calls.clear();D3D12Hooks::RestoreRoot(watched);
 need(calls.size()==2&&calls[0].name=="compute.signature"&&calls[1].name=="many"&&calls[1].parameter==2&&calls[1].offset==0&&calls[1].words==std::vector<uint64_t>{99}&&warningCalls==warnings,"ordinary unknown-root restore preserves observed argument and skips all silent unbound gaps");
 retire(NrdBridgeBirth::Capture(watched));retire(node);
 FakeObject ownedList,ownedRoot;watched=ownedList.as<ID3D12GraphicsCommandList>();root=ownedRoot.as<ID3D12RootSignature>();
 auto before=coverageCalls;FrameSurvey::internalScope=true;calls.clear();hkSetComputeRootSignature(watched,root);PublishCreatedRootParameters(root,__uuidof(ID3D12RootSignature),7);FrameSurvey::internalScope=false;
 need(calls.size()==1&&ownedList.reads==0&&ownedRoot.reads==0&&ownedRoot.writes==0&&coverageCalls==before&&!rootStates.contains(watched),"owned internal setter/create skips title bootstrap while original native call remains once");
 gNrdBridgeDeviceWrappers=false;rootSigParameterCount[root]=7;calls.clear();hkSetComputeRootSignature(watched,root);
 need(calls.size()==1&&ownedList.reads==0&&ownedRoot.reads==0&&coverageCalls==before&&rootStates.at(watched).size()==7,"startup OFF configured helper retains legacy recording with zero native stamp/coverage work");
 gNrdBridgeDeviceWrappers=true;
 need(nativeUnderBirth==0&&nativeUnderTracker==0&&healthCalls==0,"all native identity, coverage, original setters, QI references and payload drains stay outside Birth/tracker locks");
}
void rootBirthCases(){activateBirth();createdRootCases();bindingBirthCases();unknownAndOffCases();}
void rootOomCase(const std::string& kind){
 activateBirth();FakeObject listObject,rootObject;
 watched=listObject.as<ID3D12GraphicsCommandList>();root=rootObject.as<ID3D12RootSignature>();
 if(kind=="oom-created"){
  rootObject.armCountWrite=true;returnedRoot=root;deserializer.desc.Version=D3D_ROOT_SIGNATURE_VERSION_1_0;deserializer.desc.Desc_1_0.NumParameters=7;
  void* output=nullptr;const auto before=originalCreateCalls,released=deserializerReleases;
  need(hkCreateRootSignature(nullptr,0,&blob,1,__uuidof(ID3D12RootSignature),&output)==S_OK&&output==root&&originalCreateCalls==before+1&&deserializerReleases==released+1,"metadata OOM preserves successful native creator/output and releases deserializer");
 }else{
  const auto birth=NrdBridgeNativeBirth::Prepare(root);NativeRootParameterCount count{birth->InstanceStamp(),7,1};rootObject.SetPrivateData(RootParameterCountGuid,sizeof(count),&count);
  rootObject.armCountRead=true;calls.clear();hkSetComputeRootSignature(watched,root);
  need(calls.size()==1&&calls[0].name=="compute.signature","cold root count OOM preserves one original title setter");
 }
 need(oomHits==1&&!NrdBridgeBirth::Healthy()&&healthCalls==1,"actual map allocation failure latches metadata health exactly once after all guards unwind");
 need(nativeUnderBirth==0&&nativeUnderTracker==0&&!rootSigParameterCount.contains(root),"failed new metadata publication leaves no root count row and no native-under-lock calls");
}
'''


def run():
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    os.environ['FSRD_RESTORE_GENERATE_ONLY'] = '1'
    source_file = base.run()
    del os.environ['FSRD_RESTORE_GENERATE_ONLY']
    cpp = source_file.read_text()
    cpp = cpp.replace('struct Config{Option RestoreComputeSignature,RestoreGraphicSignature,ExtendedStateRestore;',
                      'struct Config{Option RestoreComputeSignature,RestoreGraphicSignature,ExtendedStateRestore; std::optional<float> MipmapBiasOverride; std::optional<int> AnisotropyOverride;')
    cpp = cpp.replace('void MetadataHookFailed(const char*) noexcept {}',
                      'void MetadataHookFailed(const char*) noexcept;')
    cpp = cpp.replace('namespace NrdBridgeNativeBirth { bool ObserveReleaseCoverage(IUnknown*) noexcept { return true; } }', '')
    cpp = cpp.replace('void blockNative(ID3D12GraphicsCommandList* list,Block kind){',
                      'void checkNativeContext();\nvoid blockNative(ID3D12GraphicsCommandList* list,Block kind){checkNativeContext();')
    production = (ROOT/'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    creator = production[production.index('struct ReturnedRootInterface'):production.index('VALIDATE_HOOK(hkCreateRootSignature')]
    creator += '\n' + function(production, 'static HRESULT hkCreateRootSignature(')
    extra = ADAPTER + '\nnamespace FrameSurvey{void MetadataHookFailed(const char*)noexcept{checkNativeContext();++healthCalls;}}\n' + creator + CASES
    cpp = cpp.replace('int main()try{', extra + '\nint main(int argc,char**argv)try{\nif(argc>1){rootOomCase(argv[1]);std::cout<<"PASS: "<<checks<<" root OOM checks\\n";return 0;}')
    cpp = cpp.replace(' rootProfilerCases();', ' rootProfilerCases();\n rootBirthCases();')
    cpp = cpp.replace(' std::cout<<"PASS: "<<checks', ' std::cout<<"PASS: "<<checks')
    file, exe = out/'root_birth.cpp', out/'root_birth.exe'
    file.write_text(cpp)
    if os.environ.get('FSRD_ROOT_BIRTH_GENERATE_ONLY') == '1':
        return file
    build = base.compile_cpp(file, exe, libraries=['bcrypt.lib'])
    (out/'build.json').write_text(json.dumps(build, indent=2))
    results = {}
    for case in ['', 'oom-created', 'oom-bootstrap']:
        result = subprocess.run([str(exe)] + ([case] if case else []), capture_output=True, text=True, timeout=30)
        key = case or 'positive'
        results[key] = {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        (out/f'{key}.stdout.txt').write_text(result.stdout)
        (out/f'{key}.stderr.txt').write_text(result.stderr)
        (out/'result.json').write_text(json.dumps({'cases': results}, indent=2))
        print(result.stdout, end='')
        print(result.stderr, end='', file=sys.stderr)
        result.check_returncode()
        results[key]['checks'] = int(result.stdout.split()[1])
    report = {'checks': sum(item['checks'] for item in results.values()), 'cases': results,
              'scope': 'actual D3D root/list hook/creator/cleanup/restore bodies, actual Birth/NativeBirth/Lifetime headers; explicit CPU byte-data COM ABI and derived native recording seams; no real runtime, physical detours, or GPU claim'}
    (out/'result.json').write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    run()
