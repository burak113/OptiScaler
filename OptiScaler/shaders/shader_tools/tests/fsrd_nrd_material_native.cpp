// Native readiness/PSO selection are synthetic. Capture, native Birth metadata,
// coordinator, shader bytecode, signed AMD RR, submission and GPU readback are real.
int main(int argc,char** argv)try{
 need(argc==3,"output directory and signed provider required");
 NativeFixture::Bootstrap();Host h;NativeFixtureRegister(h.device.Get());NativeFixtureRegister(h.list.Get());
 g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";Config::Instance()->FfxDenoiserNrdBridge.value=true;
 NrdBridge::ConfigureStartup(true);loadProvider(argv[2]);FrameSurvey::BeginCreationTracking(false);
 need(FrameSurvey::Install(h.device.Get(),h.list.Get(),false),"native metadata install");
 need(NrdBridge::Initialize(h.device.Get()),"coordinator initialize");
 AttachRoots(h.list.Get());Wiring::Attach(h.list.Get());NativeDraw::Attach(h.list.Get());NrdBridge::SetNativeElisionContractForTesting(true);
 J rows=J::array();
 {
  NativeFixture::NativeTitle title(h,false);NativeMaterialTitle writer(title);
  NrdBridge::RRSettings settings;settings.nativeMaterialGuides=true;std::string error;
  need(NrdBridge::ApplyRRSettings(settings,false,error),"enable native material guides");
  for(UINT frame=0;frame<6;++frame){
   if(frame==4||frame==5){settings.nativeMaterialGuides=frame==5;
    need(NrdBridge::ApplyRRSettings(settings,false,error),"native material OFF/ON toggle applies");}
   writer.start();writer.dispatch(frame!=0&&frame!=3);
   const auto status=NrdBridge::GetStatus();
   std::cout<<"writer frame="<<frame<<" attempts="<<status.nativeMaterialAttempts<<" snapshots="<<status.nativeMaterialSnapshots<<" unknown="<<status.nativeMaterialUnknownState<<" unsupported="<<status.nativeMaterialUnsupportedState<<" failures="<<status.nativeMaterialCaptureFailures<<std::endl;
   const bool captured=bool(NrdBridge::gService->lists.at(h.list.Get()).pendingMaterial.snapshot);
   const bool expected=frame!=0&&frame!=3&&frame!=4;
   need(captured==expected,"only known enabled same-recording sources reach native material capture");
   if(frame==3)need(status.nativeMaterialCaptureReason=="source_state_unknown",
                   "missing local state has an explicit rejection reason");
   title.Begin(frame+1);title.A();title.ConsumerA();
   auto stage=NrdBridge::gService->lists.at(h.list.Get()).native[0];
   need(stage&&stage->committed,"actual native A transaction commits");
   need(NrdBridge::GetStatus().nativeMaterialGuidesActive==captured,"native admission agrees with captured material");
   need(FfxApiProxy::lastDispatch.specularAlbedo.resource==stage->inputs.specAlbedo&&
        FfxApiProxy::lastDispatch.diffuseAlbedo.resource==stage->inputs.diffAlbedo,
        "signed provider consumes the exact guide resources being read back");
   if(frame==1){
    writer.dispatch(true);
    need(bool(NrdBridge::gService->lists.at(h.list.Get()).pendingMaterial.snapshot),
         "material writer following a committed native transaction is not silently skipped");
    writer.dispatch(false,false,true);
    need(!NrdBridge::gService->lists.at(h.list.Get()).pendingMaterial.snapshot,
         "unsupported later material writer tombstones the preceding native snapshot");
    need(NrdBridge::GetStatus().nativeMaterialCaptureReason=="format_or_subresource_profile",
         "unsupported writer exposes its exact rejection reason");
   }
   const auto s=title.readback(stage->inputs.specAlbedo,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
   const auto d=title.readback(stage->inputs.diffAlbedo,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
   const auto check=writer.captureCheck();need(NativeFixture::Execute(h),"native submission admitted");writer.validateCheck(check.Get());
   const auto sb=materialBytes(s,4),db=materialBytes(d,4);size_t nonwhite=0;
   for(size_t i=0;i<db.size();++i)if(i%4!=3)nonwhite+=db[i]!=255;
   need((nonwhite!=0)==captured,"GPU diffuse guide pixels match real-versus-white admission");
   materialSave(std::filesystem::path(argv[1])/("frame"+std::to_string(frame)+"-diff.bin"),db);
   materialSave(std::filesystem::path(argv[1])/("frame"+std::to_string(frame)+"-spec.bin"),sb);
   rows.push_back({{"frame",frame},{"captured",captured},{"requested",settings.nativeMaterialGuides},
                   {"nonwhite_diffuse_components",nonwhite},{"capture_reason",status.nativeMaterialCaptureReason}});h.reset();
  }
  h.waitComplete();NrdBridge::Shutdown();auto recording=RecordedComputeLease::Capture(h.list.Get());RecordedComputeLease::Detach(recording);RecordedComputeLease::Poll();
 }
 NativeDraw::Detach();Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();
 const auto debug=h.debugCounts();J result={{"frames",rows},{"native_checks",checks},{"debug_errors",debug[0]},{"debug_warnings",debug[1]},{"dispatches",FfxApiProxy::dispatches},{"contexts",FfxApiProxy::creates},{"destroyed",FfxApiProxy::destroys}};
 need(FfxApiProxy::creates==FfxApiProxy::destroys,"all actual provider contexts retire");
 std::ofstream(std::filesystem::path(argv[1])/"material-native-result.json")<<result.dump(2)<<'\n';
 std::cout<<"PASS material_native "<<checks<<std::endl;return 0;
}catch(const std::exception& e){std::cerr<<"FAIL material_native: "<<e.what()<<std::endl;return 1;}
