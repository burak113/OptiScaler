#include "NativeColourContract.h"
#include <cstdlib>
#include <cstring>
#include <iostream>

namespace
{
int checks=0;
void Require(bool value,const char* description)
{
    ++checks;
    if(!value) { std::cerr<<"FAIL: "<<description<<'\n'; std::exit(1); }
}
using namespace NativeColour;
Identity IdentityFor(Lobe lobe=Lobe::Diffuse)
{
    Identity x; x.frame=12; x.generation=3; x.recording=8;
    x.renderWidth=1920; x.renderHeight=1080; x.cropX=17; x.cropY=29;
    x.activeWidth=13; x.activeHeight=9; x.lobe=lobe;
    x.providerScale=lobe==Lobe::Diffuse?16:256; return x;
}
Config Active() { Config x; x.enabled=true; x.acknowledgeRejectedResearch=true; return x; }
Evidence Cert(const Identity& id)
{
    Evidence e; e.identity=id; e.authority=EvidenceKind::SyntheticFixture;
    e.support=EvidenceKind::SyntheticFixture; e.sourceStage=SourceStage::PreProviderPhysicalSnapshot;
    e.radius=3; e.producerVersion=1; return e;
}
}
int main()
{
    using namespace NativeColour;
    Config c=Active(); Frame f; f.identity=IdentityFor(); Evidence e=Cert(f.identity);
    Require(Validate(c,f,e)==Decision::Ready,"active supported fixture admitted");
    Require(Validate(Config{},f,e)==Decision::Off,"default off");
    auto q=c; q.acknowledgeRejectedResearch=false;
    Require(Validate(q,f,e)==Decision::Off,"research acknowledgment required");
    q=c; q.strength=0; Require(Validate(q,f,e)==Decision::ZeroStrength,"zero strength");
    q=c; q.maxLogDelta=0; Require(Validate(q,f,e)==Decision::ZeroStrength,"zero budget");
    f.reset=true; Require(Validate(c,f,e)==Decision::ResetOrResize,"reset identity");
    f.reset=false; f.resized=true; Require(Validate(c,f,e)==Decision::ResetOrResize,"resize identity"); f.resized=false;
    auto bad=e; bad.authority=EvidenceKind::Unknown;
    Require(Validate(c,f,bad)==Decision::UnknownAuthority,"unknown authority");
    bad=e; bad.authority=static_cast<EvidenceKind>(3);
    Require(Validate(c,f,bad)==Decision::UnknownAuthority,"reserved authority rejected");
    bad=e; bad.support=EvidenceKind::Unknown;
    Require(Validate(c,f,bad)==Decision::UnknownSupport,"unknown support");
    bad=e; bad.support=static_cast<EvidenceKind>(3);
    Require(Validate(c,f,bad)==Decision::UnknownSupport,"reserved support rejected");
    bad=e; bad.radius=2; Require(Validate(c,f,bad)==Decision::UnknownSupport,"wrong radius certificate");
    bad=e; bad.estimatorVersion=2; Require(Validate(c,f,bad)==Decision::UnknownSupport,"wrong estimator certificate");
    bad=e; bad.producerVersion=0; Require(Validate(c,f,bad)==Decision::UnknownSupport,"missing producer provenance");
    bad=e; bad.sourceStage=SourceStage::Unknown;
    Require(Validate(c,f,bad)==Decision::UnsupportedSource,"restored source cannot masquerade as original");
    auto id=f.identity;
    for(int which=0;which<12;++which)
    {
        auto x=id;
        switch(which) {
        case 0:++x.frame;break; case 1:++x.generation;break; case 2:++x.recording;break;
        case 3:++x.renderWidth;break; case 4:++x.renderHeight;break; case 5:++x.cropX;break;
        case 6:++x.cropY;break; case 7:++x.activeWidth;break; case 8:++x.activeHeight;break;
        case 9:x.lobe=Lobe::Specular;break; case 10:x.providerScale=256;break;
        case 11:x.recording=0;break; }
        bad=e; bad.identity=x;
        Require(Validate(c,f,bad)==Decision::InvalidIdentity,"stale/cross-role identity rejected");
    }
    Require(ValidIdentity(IdentityFor(Lobe::Specular)),"S256 native identity");
    auto invalid=id; invalid.providerScale=256; Require(!ValidIdentity(invalid),"D256 not D16");
    invalid=id; invalid.cropX=-1; Require(!ValidIdentity(invalid),"negative crop");
    invalid=id; invalid.cropX=1910; Require(!ValidIdentity(invalid),"crop exceeds render");
    invalid=id; invalid.activeHeight=0; Require(!ValidIdentity(invalid),"empty active");
    invalid=id; invalid.generation=0; Require(!ValidIdentity(invalid),"unknown generation");
    invalid=id; invalid.lobe=static_cast<Lobe>(9); Require(!ValidIdentity(invalid),"invalid lobe");
    constexpr float inf=std::numeric_limits<float>::infinity();
    constexpr float nan=std::numeric_limits<float>::quiet_NaN();
    const float badScales[] {0,-1,inf,nan,1e-30f,1e30f};
    for(float v:badScales)
    {
        q=c; q.spatialSigma=v; Require(!ValidConfig(q),"invalid stored/squared sigma");
        q=c; q.guideChromaRadius=v; Require(!ValidConfig(q),"invalid stored/squared colour radius");
    }
    q=c; q.spatialSigma=static_cast<float>(1e-300); Require(!ValidConfig(q),"FP64 to FP32 underflow caught");
    q=c; q.spatialSigma=static_cast<float>(1e300); Require(!ValidConfig(q),"FP64 to FP32 overflow caught");
    for(float v:{-1.0f,1.01f,inf,nan})
    { q=c; q.strength=v; Require(!ValidConfig(q),"invalid strength rejected"); }
    q=c; q.normalCosine=1; Require(!ValidConfig(q),"zero normal denominator");
    q=c; q.normalCosine=-1.01f; Require(!ValidConfig(q),"out of domain normal");
    q=c; q.normalCosine=nan; Require(!ValidConfig(q),"nan normal");
    q=c; q.radius=9; Require(!ValidConfig(q),"excess radius");
    q=c; q.representation=static_cast<Representation>(2); Require(!ValidConfig(q),"invalid representation");
    q=c; q.maxLogDelta=2.01f; Require(!ValidConfig(q),"excess log gain");
    q=c; q.supportPrior=-1; Require(!ValidConfig(q),"negative sample prior");
    q=c; q.roughnessTolerance=std::numeric_limits<float>::denorm_min();
    Require(!ValidConfig(q),"GPU FTZ roughness denominator rejected");
    q=c; q.depthTolerance=std::numeric_limits<float>::denorm_min();
    Require(!ValidConfig(q),"GPU FTZ depth denominator rejected");
    q=c; q.strength=std::numeric_limits<float>::denorm_min();
    Require(!ValidConfig(q),"GPU FTZ nonzero strength rejected");
    q=c; q.maxLogDelta=std::numeric_limits<float>::denorm_min();
    Require(!ValidConfig(q),"GPU FTZ nonzero gain budget rejected");
    q=c; q.supportPrior=std::numeric_limits<float>::denorm_min();
    Require(!ValidConfig(q),"GPU FTZ nonzero prior rejected");
    q=c; q.normalCosine=-std::numeric_limits<float>::denorm_min();
    Require(!ValidConfig(q),"GPU FTZ subnormal normal threshold rejected");
    q=c; q.enabled=false; q.strength=nan;
    Require(Validate(q,f,e)==Decision::InvalidConfig,"invalid config rejected even OFF");

    Layout l {17,12,256,512,4096};
    Require(ValidLayout(l,13,9),"unequal allocation active fits");
    auto wrong=l; wrong.bytes=512+11*256+17*8;
    Require(!ValidLayout(wrong,13,9),"D3D footprint total omits last row padding");
    wrong=l; wrong.offset=4; Require(!ValidLayout(wrong,13,9),"misaligned offset");
    wrong=l; wrong.rowPitch=136; Require(!ValidLayout(wrong,13,9),"unpitched row");
    wrong=l; wrong.width=33; Require(!ValidLayout(wrong,13,9),"pitch smaller than allocation");
    wrong=l; wrong.bytes=4095; Require(!ValidLayout(wrong,13,9),"RAW view byte alignment");
    wrong=l; wrong.offset=uint64_t(UINT32_MAX)+1;
    wrong.bytes=wrong.offset+4096; Require(!ValidLayout(wrong,13,9),"uint32 address overflow");
    wrong=l; wrong.offset=UINT32_MAX-511; wrong.bytes=UINT32_MAX-3;
    Require(!ValidLayout(wrong,13,9),"last texel crossing byteaddress end");
    Require(!ValidLayout(l,18,9),"active width beyond allocation");
    Require(!ValidLayout(l,13,13),"active height beyond allocation");
    Require(!ValidLayout(l,0,9),"empty dispatch extent");
    std::array<Layout,4> layouts {l,Layout{19,14,512,1024,9216},l,l};
    Require(ValidLayouts(layouts,13,9),"independent source raw selected footprints");
    layouts[3].rowPitch=512;
    Require(!ValidLayouts(layouts,13,9),"selected output entire buffer layout must match");
    layouts[3]=l;
    const auto constants=MakeConstants(c,f,layouts);
    Require(constants.extent==std::array<uint32_t,4>{13,9,17,12},"active distinct from allocation constants");
    Require(constants.rowPitch[1]==512 && constants.byteOffset[1]==1024 && constants.byteSize[1]==9216,
            "per-resource layout constants");
    Require(constants.control==std::array<uint32_t,4>{1,0,3,1},"research enabled explicit version");
    Require(constants.support[2]==c.normalCosine && constants.colour[3]==c.strength,"float32 constants exact");
    Require(sizeof(constants)==112 && alignof(Constants)==16 && ConstantAllocationBytes==256,"cbuffer ABI");
    std::cout<<"PASS "<<checks<<" host contract assertions (CPU only; no D3D12 execution)\n";
    return 0;
}
