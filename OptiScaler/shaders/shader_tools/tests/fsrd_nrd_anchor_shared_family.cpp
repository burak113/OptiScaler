// Actual RRWrapper/anchor allocation and Service-family sharing contract.
// The two route predicates are extracted verbatim from the coordinator source.
#include <filesystem>
#include <fstream>
#include <json.hpp>
#define main OriginalRRFixtureMain
#include "nrd_bridge_rr_fixture.cpp"
#undef main
#include "source_family_gates.h"

void NativeProviderBoundary(ID3D12GraphicsCommandList*,ID3D12Resource*,ID3D12Resource*) {}
static bool legacyGateMutant=false;

static bool gate(unsigned route,bool ready,const RRSettings& settings)
{
    if(legacyGateMutant)return ready&&settings.lobeRecovery&&
        (settings.recoverySpecular>0.f||settings.recoveryDiffuse>0.f);
    return route==0?ConvertedFamilyGate(ready,settings):NativeFamilyGate(ready,settings);
}
static void policyChecks()
{
    for(unsigned route=0;route<2;++route)for(bool ready:{false,true})for(bool lobe:{false,true})
    for(float spec:{0.f,.5f})for(float diff:{0.f,.5f})for(bool anchor:{false,true})for(float strength:{0.f,1.f})
    {
        RRSettings s;s.lobeRecovery=lobe;s.recoverySpecular=spec;s.recoveryDiffuse=diff;
        s.postMotionAnchor=anchor;s.postMotionAnchorStrength=strength;
        const bool old=ready&&lobe&&(spec>0.f||diff>0.f);
        const bool expected=ready&&((lobe&&(spec>0.f||diff>0.f))||(anchor&&strength>0.f));
        need(gate(route,ready,s)==expected,"both exact coordinator predicates match effective anchor/lobe policy");
        if(!anchor||strength==0.f)need(gate(route,ready,s)==old,"OFF and zero-strength coordinator policy preserves old behavior");
    }
}

static void attach(unsigned route,RRWrapper& wrapper,const RRSettings& settings,std::shared_ptr<RRRecoveryFamily>& service)
{
    std::string error;need(wrapper.Configure(settings,error),error.c_str());
    if(gate(route,true,settings))
    {
        if(!service)service=CreateRRRecoveryFamily();
        wrapper.SetRecoveryFamily(service);
    }
}

static void record(Host& host,Scene& scene,RRWrapper& wrapper,uint32_t token,bool fallback)
{
    std::string error;FrameParameters frame;
    need(wrapper.PrepareFrame(camera(token),true,frame,error),error.c_str());
    RRRecordedOutputLease output;
    need(wrapper.RecordOwned(host.list.Get(),scene.resources,frame,output,error),error.c_str());
    const auto snapshot=wrapper.GetOwnedOutputSnapshot(output);
    need(snapshot.postMotionAnchorFallback==fallback,"shared Service family controls actual anchor admission across domains");
    if(fallback)
    {
        need(snapshot.postMotionAnchorError.find("shared graph byte limit reached")!=std::string::npos,
            "shared-family capacity produces the exact optional anchor budget fallback");
        need(!output->lease->inputAnchor.owner,"budget-rejected domain retains no private replacement anchor graph");
    }
    else need(bool(output->lease->inputAnchor.owner),"admitted domain owns actual prepared native anchor graph");
    need(wrapper.CommitOwned(host.list.Get(),output,scene.spec(),scene.diff(),frame,error),error.c_str());
    host.submit();host.reset();output.reset();RecordedComputeLease::Poll();
}

// Synthetic accounting pressure uses the actual shared atomic counter; it does
// not allocate 2GiB of GPU memory or replace the production budget admission.
struct AccountingPressure
{
    std::shared_ptr<RRRecoveryFamily> family;uint64_t bytes=0;
    explicit AccountingPressure(const std::shared_ptr<RRRecoveryFamily>& f):family(f)
    {
        const auto old=f->budget.graphBytes.load();bytes=LobeRecovery::Family::GraphByteLimit-old;
        f->budget.graphBytes.fetch_add(bytes);
    }
    ~AccountingPressure(){family->budget.graphBytes.fetch_sub(bytes);}
};

int main(int argc,char** argv) try
{
    need(argc==2||argc==3,"output folder and optional legacy-gate mutant required");
    legacyGateMutant=argc==3;const auto out=std::filesystem::path(argv[1]);std::filesystem::create_directories(out);
    if(!legacyGateMutant)policyChecks();
    Host host;Scene scene(host,64,64,{},true);host.submit();host.reset();FfxApiProxy::recordPartialWrites=true;
    RRSettings settings;settings.postMotionAnchor=true;settings.postMotionAnchorStrength=1.f;
    std::shared_ptr<RRRecoveryFamily> service;
    uint64_t one=0,two=0,three=0;
    {
        RRWrapper a,b,c;
        attach(0,a,settings,service);record(host,scene,a,100,false);
        need(bool(service),"actual anchor domain uses Service family even with lobe recovery OFF");
        one=SnapshotRecoveryFamilyMemory(service).graphBytes;need(one>0,"first anchor domain charges Service graph bytes");
        attach(1,b,settings,service);record(host,scene,b,200,false);
        two=SnapshotRecoveryFamilyMemory(service).graphBytes;
        need(two>one&&SnapshotRecoveryFamilyMemory(service).slots>=2,"second route/domain accumulates into the SAME Service graph and slot budget");
        attach(1,c,settings,service);
        {
            AccountingPressure pressure(service);record(host,scene,c,300,true);
            need(SnapshotRecoveryFamilyMemory(service).graphBytes==LobeRecovery::Family::GraphByteLimit,
                "denied third domain cannot escape into a private family or leak a graph charge");
        }
        need(SnapshotRecoveryFamilyMemory(service).graphBytes==two,"removing synthetic pressure restores both real domain charges exactly");
        record(host,scene,c,301,false);three=SnapshotRecoveryFamilyMemory(service).graphBytes;
        need(three>two,"same third domain recovers after shared capacity becomes available");
    }
    RecordedComputeLease::Poll();
    const auto retired=SnapshotRecoveryFamilyMemory(service);
    need(retired.graphBytes==0&&retired.slotBytes==0&&retired.slots==0,"all domain graph/slot charges retire exactly after completion and wrapper release");
    for(unsigned route=0;route<2;++route)
    {
        RRSettings off;std::shared_ptr<RRRecoveryFamily> none;RRWrapper wrapper;attach(route,wrapper,off,none);
        need(!none,"anchor/lobe OFF creates no Service family");
        off.postMotionAnchor=true;off.postMotionAnchorStrength=0;attach(route,wrapper,off,none);
        need(!none,"anchor strength zero creates no Service family");
    }
    hr(host.list->Close());RecordedComputeLease::Poll();host.checkDebug();
    need(FfxApiProxy::creates==FfxApiProxy::destroys,"provider contexts balance across all native family domains");
    nlohmann::json result={{"checks",checks},{"first_domain_graph_bytes",one},{"second_domain_graph_bytes",two},
        {"third_domain_graph_bytes",three},{"debug_errors",0},{"debug_warnings",0},
        {"scope","Exact two coordinator predicates plus actual native RRWrapper/anchor allocation and shared budget admission; synthetic accounting pressure, mock provider, no game/AMD quality claim"}};
    std::ofstream(out/"shared_family_result.json")<<result.dump(2);
    std::cout<<"PASS native_anchor_shared_family checks="<<checks<<" debug_errors=0 debug_warnings=0\n";return 0;
}
catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}
