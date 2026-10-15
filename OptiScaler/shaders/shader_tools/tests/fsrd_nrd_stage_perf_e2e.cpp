// Appended to the unchanged, generated production E2E translation unit after
// renaming its original main. Creation/lifetime seams are the existing adapters.
// Only the StagePerf header's QPC calls and the logger sink are observed here.
std::atomic<uint64_t> stageCounterCalls{0},stageFrequencyCalls{0};
BOOL WINAPI StageCountedCounter(LARGE_INTEGER* value) {stageCounterCalls.fetch_add(1,std::memory_order_relaxed);return ::QueryPerformanceCounter(value);}
BOOL WINAPI StageCountedFrequency(LARGE_INTEGER* value) {stageFrequencyCalls.fetch_add(1,std::memory_order_relaxed);return ::QueryPerformanceFrequency(value);}
unsigned stageLogCalls=0,stageFlushCalls=0,otherFlushCalls=0;
bool stageFlushArmed=false,stageCallbackOk=true,stageCallbackLocksFree=false,stageCallbackBindings=false;
std::string stageLogLine;
ID3D12RootSignature* stageExpectedRoot=nullptr;
std::vector<ID3D12DescriptorHeap*> stageExpectedHeaps;
uint64_t stageExpectedSrv=0,stageExpectedUav=0;

void StageFixtureLog(std::string_view format,std::string_view text) noexcept {
 try {
  ++stageLogCalls;stageFlushArmed=true;stageLogLine=std::string(format.substr(0,format.find("{}")))+std::string(text);
  stageCallbackOk=stageCallbackOk&&NrdBridge::gStageCollector.Accepted()==100&&NrdBridge::gStagesStopped.load(std::memory_order_acquire)&&
   NrdBridgeLifetime::Detail::borrowDepth==0&&NrdBridgeLifetime::Detail::releaseDepth==0&&!FrameSurvey::Internal();
  unsigned unlocked=0;
  // Every worker operation is nonblocking. Exclusive physical try_lock also
  // detects a legacy shared ScopedBorrow left alive on the reporting thread.
  std::thread worker([&]{
   if(NrdBridge::gMutex.try_lock()){unlocked|=1;NrdBridge::gMutex.unlock();}
   if(NrdBridge::gInjectionMutex.try_lock()){unlocked|=2;NrdBridge::gInjectionMutex.unlock();}
   if(NrdBridgeLifetime::Detail::Mutex().try_lock()){unlocked|=4;NrdBridgeLifetime::Detail::Mutex().unlock();}
  });worker.join();stageCallbackLocksFree=unlocked==7;
  FrameSurvey::ComputeBindings current;
  stageCallbackBindings=D3D12Hooks::GetComputeBindingsForBridge(requestedList,current)&&current.root==stageExpectedRoot&&current.heaps==stageExpectedHeaps;
  bool srv=false,uav=false;for(const auto& table:current.tables){if(table.first==1)srv=table.second.ptr==stageExpectedSrv;if(table.first==5)uav=table.second.ptr==stageExpectedUav;}
  stageCallbackBindings=stageCallbackBindings&&srv&&uav;
  stageCallbackOk=stageCallbackOk&&stageCallbackLocksFree&&stageCallbackBindings;
  std::cout<<stageLogLine<<'\n';std::cout.flush();
 }catch(...){stageCallbackOk=false;}
}
void StageFixtureFlush() noexcept {if(stageFlushArmed){stageFlushArmed=false;++stageFlushCalls;}else ++otherFlushCalls;}

void stageNoEarlyReport(uint32_t accepted,const char* context){
 need(NrdBridge::gStageCollector.Accepted()==accepted,context);
 need(stageLogCalls==0&&stageFlushCalls==0&&!NrdBridge::gStagesStopped.load(std::memory_order_acquire),"stages reporter remains silent before one hundred committed unique Consumer IDs");
}
void stageSuccess(Host& host,Title& title,uint32_t frame,uint32_t accepted,bool stopped){
 const auto provider=FfxApiProxy::dispatches,restore=restores;const auto bridged=NrdBridge::GetStatus().framesBridged;
 title.frame(frame);
 need(FfxApiProxy::dispatches==provider+1&&NrdBridge::GetStatus().active&&NrdBridge::GetStatus().framesBridged==bridged+1,"StagePerf success records actual signed RR and exactly one title output commit");
 need(restores==restore+3,"StagePerf success executes the actual Recon/motion/RR restore paths");
 const auto& list=NrdBridge::gService->lists.at(host.list.Get());
 need(list.recording&&list.recording->outputCommitted.load(std::memory_order_acquire),"successful sample has an actual production committed recording token");
 need(NrdBridge::gStageCollector.Accepted()==accepted,"collector accepts only the expected committed unique IDs");
 need(NrdBridge::gStagesStopped.load(std::memory_order_acquire)==stopped,"collection stops exactly at its one hundredth unique committed output");
 title.rrChecks(title.finish());
}

int main(int argc,char** argv)try{
 need(argc==3,"StagePerf fixture requires scratch output and signed AMD DLL");
 const auto output=std::filesystem::path(argv[1]);g_dllPath=output/"fixture.dll";Host host;requestedList=host.list.Get();
 need(!NrdBridgeNativeBirth::Ready()&&!NrdBridgeLifetime::ConcurrentReleasesEnabled(),"StagePerf fixture retains the declared legacy native-lifetime adapter boundary");
 need(NrdBridge::gStageCollector.Accepted()==0&&!NrdBridge::gStagesStopped.load(),"fresh process has an empty one-shot stage collector");
 AttachRoots(host.list.Get());Wiring::Attach(host.list.Get());
 {Title disabled(host,128,128,false);disabled.frame(0,3,2,false);need(disabled.sentinel(disabled.finish(3,2,false)),"startup OFF executes original title NRD with untouched sentinel RGBA");}
 need(stageCounterCalls==0&&stageFrequencyCalls==0&&FfxApiProxy::dispatches==0,"startup OFF performs no StagePerf clock or real provider work");
 Wiring::Detach();DetachRoots();Config::Instance()->FfxDenoiserNrdBridge.value=true;NrdBridge::ConfigureStartup(true);loadProvider(argv[2]);
 FrameSurvey::BeginCreationTracking(false);need(FrameSurvey::Install(host.device.Get(),host.list.Get(),false),"actual metadata-only survey installs for StagePerf full-host proof");
 need(NrdBridge::Initialize(host.device.Get()),"actual production coordinator initializes");AttachRoots(host.list.Get());Wiring::Attach(host.list.Get());
 Title title(host,128,128,true);stageExpectedRoot=title.root.Get();stageExpectedHeaps={title.visible.Get(),title.sampler.Get()};
 stageExpectedSrv=title.visible->GetGPUDescriptorHandleForHeapStart().ptr;stageExpectedUav=stageExpectedSrv+uint64_t(48)*title.increment;
 for(UINT menu=0;menu<4;++menu){StreamlineHooks::snapshot=camera(500+menu,title.width,title.height);NrdBridge::OnPresent();}
 stageNoEarlyReport(0,"menu/evaluation metadata without a successful Consumer accepts zero samples");need(stageCounterCalls==0&&stageFrequencyCalls==0,"menu-only activity performs no StagePerf clock calls");
 title.frame(1);need(title.sentinel(title.finish()),"discovery executes untouched original native NRD");stageNoEarlyReport(0,"discovery-only Consumer does not fill a successful-output sample");
 std::cerr<<"StagePerf actual success/duplicate controls\n";
 stageSuccess(host,title,1000,1,false);stageNoEarlyReport(1,"first unique real output accepts one sample");
 stageSuccess(host,title,1000,1,false);stageNoEarlyReport(1,"a second real committed output with duplicate SL ID is excluded");
 need(stageCounterCalls>0&&stageFrequencyCalls==0,"actual stage timers call real QPC while no premature report frequency is queried");
 const auto beforeCancel=FfxApiProxy::dispatches;const auto cancelFrames=NrdBridge::GetStatus().framesBridged;
 FfxApiProxy::afterRealDispatch=+[]{NrdBridge::RequestHistoryReset();};title.frame(1001);FfxApiProxy::afterRealDispatch=nullptr;
 need(FfxApiProxy::dispatches==beforeCancel+1&&NrdBridge::GetStatus().framesBridged==cancelFrames,"SDK-success cancellation records real provider work without publishing Consumer output");
 need(title.sentinel(title.finish()),"SDK-success cancellation preserves original native title output RGBA");stageNoEarlyReport(1,"canceled output never accepts a stage sample");
 stageSuccess(host,title,1002,2,false);
 const auto beforeFailure=FfxApiProxy::dispatches;const auto failureFrames=NrdBridge::GetStatus().framesBridged;
 FfxApiProxy::partialFailure=true;title.frame(1003);FfxApiProxy::partialFailure=false;
 need(FfxApiProxy::dispatches==beforeFailure+1&&NrdBridge::GetStatus().framesBridged==failureFrames,"actual provider work followed by adapter runtime failure commits no output");
 need(title.sentinel(title.finish()),"failed provider recording preserves native title sentinel RGBA");stageNoEarlyReport(2,"failed provider output never accepts a stage sample");
 const auto menuClocks=stageCounterCalls.load();for(UINT menu=0;menu<64;++menu)NrdBridge::OnPresent();
 need(stageCounterCalls==menuClocks,"retry/loading Presents do not execute stage clocks");stageNoEarlyReport(2,"retry/loading Presents never fill failed samples");
 NrdBridge::SetRuntimeEnabled(false);NrdBridge::SetRuntimeEnabled(true);
 uint64_t stoppedClocks=0,stoppedFrequency=0;J frames=J::array();
 for(UINT index=0;index<103;++index){const UINT sl=1004+index,accepted=std::min(100u,index+3);const bool stopped=accepted==100;
  const auto clocks=stageCounterCalls.load();stageSuccess(host,title,sl,accepted,stopped);
  if(!stopped)stageNoEarlyReport(accepted,"successful unique Consumer prefix has no early stage line");
  else{need(stageLogCalls==1&&stageFlushCalls==1&&stageCallbackOk,"one real stages line/flush publishes after all host/injection/physical locks and restored bindings");
   if(index==97){stoppedClocks=stageCounterCalls.load();stoppedFrequency=stageFrequencyCalls.load();need(stoppedClocks>0&&stoppedFrequency==1,"the hundredth unique output builds one frequency-bearing real report");}
   else need(stageCounterCalls==stoppedClocks&&stageFrequencyCalls==stoppedFrequency&&clocks==stoppedClocks,"later actual signed RR and committed outputs perform zero StagePerf QPC/frequency calls");}
  frames.push_back({{"sl",sl},{"accepted",accepted},{"reported",stageLogCalls},{"stage_qpc_calls",stageCounterCalls.load()}});
 }
 need(NrdBridge::GetStatus().framesBridged==106,"more than one hundred unique actual output recordings plus duplicate remain real bridge work");
 const auto beforeRestart=FfxApiProxy::dispatches;NrdBridge::SetRuntimeEnabled(false);for(UINT i=0;i<8;++i)NrdBridge::OnPresent();NrdBridge::SetRuntimeEnabled(true);
 stageSuccess(host,title,2000,100,true);need(FfxApiProxy::dispatches==beforeRestart+1&&stageCounterCalls==stoppedClocks&&stageFrequencyCalls==stoppedFrequency,"runtime recovery still dispatches real RR without rearming or reading the stopped StagePerf clock");
 need(stageLogCalls==1&&stageFlushCalls==1,"runtime cycling never emits a second stages line or flush");
 NrdBridge::Shutdown();RecordedComputeLease::Poll();need(FfxApiProxy::destroys==FfxApiProxy::creates&&FfxApiProxy::contextToType.empty(),"actual provider contexts retire after every completed GPU recording lease");
 Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=host.debugCounts();
 J result{{"native_checks",checks},{"debug_errors",debug[0]},{"debug_warnings",debug[1]},{"stages_log_calls",stageLogCalls},{"stages_flush_calls",stageFlushCalls},{"other_flush_calls",otherFlushCalls},
  {"accepted",NrdBridge::gStageCollector.Accepted()},{"real_successful_outputs",107},{"unique_successful_outputs",106},{"provider_dispatches",FfxApiProxy::dispatches},{"stage_qpc_calls",stoppedClocks},{"stage_frequency_calls",stoppedFrequency},
  {"callback_outside_mutex_injection_physical",stageCallbackLocksFree},{"callback_title_bindings_restored",stageCallbackBindings},{"stage_line",stageLogLine},{"frames",frames},
  {"scope","actual coordinator/conversion/RR/restore and signed AMD; StagePerf-only native-QPC counting facade; creation/proxy/legacy lifetime adapters; instrumented CPU spans are not game timings or GPU/display FPS"}};
 std::ofstream(output/"stage-perf-e2e-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS stage_perf_e2e checks="<<checks<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<"StagePerf E2E failure: "<<error.what()<<'\n';return 1;}
