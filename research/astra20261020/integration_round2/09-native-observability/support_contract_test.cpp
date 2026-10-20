#include "OptiScaler/shaders/fsrd_preprocess/FSRDNrdSupportContract.h"
#include <algorithm>
#include <iostream>
#include <limits>
#include <string>

namespace sc = NrdBridge::SupportContract;
static int failures = 0, checks = 0;
static bool mutant = false;
static void Check(bool ok, const char* name)
{
    ++checks;
    if (!ok) { ++failures; std::cerr << "FAIL " << name << '\n'; }
}

static sc::Domain Domain()
{
    sc::Domain d;
    d.activeWidth = d.activeHeight = 128; d.allocationWidth = 144; d.allocationHeight = 136;
    d.cropWidth = d.cropHeight = 128;
    d.gridWidth = d.gridHeight = 16; d.depthSign = 1; d.basisId = 1; d.resetEpoch = 7; d.frame = 20;
    return d;
}
static std::array<sc::Pixel,64> Pixels(uint32_t x, uint32_t y, double z = 5, int32_t sign = 1)
{
    std::array<sc::Pixel,64> pixels;
    for (uint32_t i = 0; i < 64; ++i)
        pixels[i] = {{double(x*8+i%8)+.5, double(y*8+i/8)+.5,z}, {0,0,1}, z*sign, true,true};
    return pixels;
}
static sc::CellCertificate Cell(sc::Domain d, uint32_t x, uint32_t y, double z = 5)
{
    auto p = Pixels(x,y,z,d.depthSign); return sc::CertifyCell(d,x,y,p.data(),p.size());
}
static sc::Footprint Good(sc::Domain d = Domain(), uint32_t x = 7, uint32_t y = 7)
{
    sc::Footprint f; f.recipient = Cell(d,x,y); f.step = 3; f.globalVetoObserved = true;
    for (uint32_t i = 0; i < 9; ++i)
    {
        auto& t = f.taps[i];
        const auto cx = uint32_t(std::max(0,std::min(int(d.gridWidth)-1,int(x)+(int(i%3)-1)*3)));
        const auto cy = uint32_t(std::max(0,std::min(int(d.gridHeight)-1,int(y)+(int(i/3)-1)*3)));
        t.current = Cell(d,cx,cy); t.weight = 1; t.weightObserved = true;
        auto& k = t.recall; k.observed = k.keyValid = k.exactFractionsObserved = true;
        k.slot = 2; k.resetEpoch = d.resetEpoch; k.frame = d.frame-1;
        k.selectedGeneration = k.capturedGeneration = 12; k.submittedFence = k.completedFence = 101;
        k.submittedTimeline = k.completedTimeline = 1;
        // Explicit synthetic sampler fractions, no inference from cropped motion.
        k.gridX = 6.25; k.gridY = 6.5;
        auto kd = d; --kd.frame;
        for (uint32_t j = 0; j < 4; ++j)
        {
            k.taps[j].cell = Cell(kd,6+j%2,6+j/2);
            k.taps[j].weight = (j%2 ? .25 : .75)*.5;
        }
    }
    return f;
}

// Deliberately broken strategy: attach the current cell's geometry to an already
// mixed gain and manufacture a complete-looking donor certificate. The SAME
// invariant tests below must reject this implementation by exiting nonzero.
static sc::Certificate Evaluate(const sc::Footprint& f)
{
    if (!mutant) return sc::Produce(f);
    sc::Certificate c; c.domain = f.recipient.domain; c.reasons = sc::ValidateCell(f.recipient);
    c.scope = 1; c.step = f.step; c.recipientX = f.recipient.x; c.recipientY = f.recipient.y;
    c.observedTapMask = sc::NativeTapMask; c.nonzeroDonors = 9; c.nonzeroKeyDonors = 36;
    c.valid = c.reasons == 0; return c;
}
static bool Accepted(const sc::Footprint& f)
{ return sc::Accepts(Evaluate(f),f.recipient.domain,f.step,f.recipient.x,f.recipient.y); }
static void Reject(sc::Footprint f, sc::Reason reason, const char* name)
{
    const auto c = Evaluate(f);
    Check(!sc::Accepts(c,f.recipient.domain,f.step,f.recipient.x,f.recipient.y) && (c.reasons&sc::Bits(reason)),name);
}

int main(int argc, char** argv)
{
    mutant = argc > 1 && std::string(argv[1]) == "--mutant-current-cell-only";
    const auto good = Good();
    Check(Accepted(good),"complete +/-3 actual donor and key support accepted");
    auto d = Domain(); d.depthSign = -1;
    Check(Accepted(Good(d)),"original negative depth convention accepted");
    Check(Accepted(Good(Domain(),0,0)),"native clamped duplicate estimator taps retained");

    auto f = good; f.taps[8].current = Cell(Domain(),10,10,2);
    Reject(f,sc::Reason::ThinOrMixedSurface,"far +3 donor contaminates pure recipient");
    f = good; f.taps[0].current = Cell(Domain(),4,4,2); f.taps[0].weight = 1e-30;
    Reject(f,sc::Reason::ThinOrMixedSurface,"tiny positive donor cannot be dropped");
    f.taps[0].weight = 0;
    Check(Accepted(f),"exact zero foreign donor adds no radiance support");
    f = good; auto kd = Domain(); --kd.frame;
    f.taps[4].recall.taps[3].cell = Cell(kd,7,7,2);
    Reject(f,sc::Reason::ThinOrMixedSurface,"foreign recalled bilinear donor rejected");

    auto p = Pixels(7,7); p[7].position.z = 2; p[7].signedDepth = 2;
    f = good; f.recipient = sc::CertifyCell(Domain(),7,7,p.data(),p.size());
    Reject(f,sc::Reason::ThinOrMixedSurface,"one-pixel surface outside sparse Stats taps rejected");
    p = Pixels(7,7); p[11].signedDepth = -5;
    f = good; f.recipient = sc::CertifyCell(Domain(),7,7,p.data(),p.size());
    Reject(f,sc::Reason::DepthSign,"depth sign mismatch is not abs-repaired");
    p[11].signedDepth = 0;
    f.recipient = sc::CertifyCell(Domain(),7,7,p.data(),p.size());
    Reject(f,sc::Reason::DepthSign,"zero depth rejected");
    p = Pixels(7,7); p[2].position.z = std::numeric_limits<double>::quiet_NaN();
    f.recipient = sc::CertifyCell(Domain(),7,7,p.data(),p.size());
    Reject(f,sc::Reason::NonFinite,"NaN geometry rejected");
    p = Pixels(7,7); p[2].signedDepth = std::numeric_limits<double>::infinity();
    f.recipient = sc::CertifyCell(Domain(),7,7,p.data(),p.size());
    Reject(f,sc::Reason::NonFinite,"infinite depth rejected");
    p = Pixels(7,7); p[2].normal = {0,0,0};
    f.recipient = sc::CertifyCell(Domain(),7,7,p.data(),p.size());
    Reject(f,sc::Reason::NonFinite,"zero normal rejected");
    p = Pixels(7,7);
    for (auto& pixel:p) { pixel.position = {0,0,0}; pixel.normal = {1,-1,0}; }
    const double largest = std::numeric_limits<double>::max();
    p[0].position = {largest,largest,0}; p[1].position = {-largest,-largest,0};
    p[63].position = {-largest,-largest,0};
    f.recipient = sc::CertifyCell(Domain(),7,7,p.data(),p.size());
    Reject(f,sc::Reason::NonFinite,"finite pixels with NaN intermediate plane residual rejected");
    auto hugeA = good.recipient, hugeB = good.recipient;
    hugeA.position = {largest,largest,largest}; hugeB.position = {0,0,0};
    const double unit = 1/std::sqrt(3.0);
    hugeA.normal = hugeB.normal = {unit,unit,-unit};
    Check((sc::Compatible(hugeA,hugeB,{})&sc::Bits(sc::Reason::NonFinite)) != 0,
          "finite cell delta with overflowing plane dot rejected as nonfinite");
    p = Pixels(7,7); p[2].observed = false;
    f.recipient = sc::CertifyCell(Domain(),7,7,p.data(),p.size());
    Reject(f,sc::Reason::UnobservedSample,"unobserved full-cell pixel stays unknown");
    p = Pixels(7,7); p[2].correspondenceKnown = false;
    f.recipient = sc::CertifyCell(Domain(),7,7,p.data(),p.size());
    Reject(f,sc::Reason::UnavailableCorrespondence,"unavailable correspondence stays unknown");
    p = Pixels(7,7);
    f.recipient = sc::CertifyCell(Domain(),7,7,p.data(),63);
    Reject(f,sc::Reason::IncompleteCell,"partial cell cannot be certified");

    f = good; f.taps[0].weightObserved = false;
    Reject(f,sc::Reason::UnavailableDonorFootprint,"unobserved tap is not assumed zero");
    f = good; f.taps[0].current.x = 6;
    Reject(f,sc::Reason::WrongFootprint,"+/-1 stencil cannot replace actual +/-3");
    f = good; f.taps[0].weight = std::numeric_limits<double>::quiet_NaN();
    Reject(f,sc::Reason::InvalidWeight,"NaN donor weight rejected");
    f = good; f.taps[0].weight = -.1;
    Reject(f,sc::Reason::InvalidWeight,"negative donor weight rejected");
    f = good; for (auto& t:f.taps) t.weight = 0;
    Reject(f,sc::Reason::NoNonzeroDonors,"empty support does not certify a correction");
    f = good; f.taps[0].current.normal.x = std::numeric_limits<double>::quiet_NaN();
    Reject(f,sc::Reason::NonFinite,"corrupt deserialized normal cannot bypass finite check");

    f = good; f.taps[0].recall.observed = false;
    Reject(f,sc::Reason::UnavailableKeyCorrespondence,"current tag cannot certify missing key");
    f = good; f.taps[0].recall.exactFractionsObserved = false;
    Reject(f,sc::Reason::UnavailableKeyCorrespondence,"ideal sampler fractions are not observed fractions");
    f = good; ++f.taps[0].recall.resetEpoch;
    Reject(f,sc::Reason::StaleEpoch,"stale recalled epoch rejected");
    f = good; f.taps[0].recall.completedFence = 100;
    Reject(f,sc::Reason::UnpublishedKey,"recorded or uncompleted key cannot be published");
    f = good; f.taps[0].recall.completedTimeline = 2;
    Reject(f,sc::Reason::UnpublishedKey,"unrelated completion fence cannot publish key");
    f = good; f.taps[0].recall.completedFence = std::numeric_limits<uint64_t>::max();
    Reject(f,sc::Reason::UnpublishedKey,"device-removal fence sentinel cannot publish support");
    f = good; f.taps[0].recall.submittedFence = f.taps[0].recall.completedFence = std::numeric_limits<uint64_t>::max();
    Reject(f,sc::Reason::UnpublishedKey,"sentinel submission cannot publish support");
    f = good; f.taps[0].recall.keyValid = false;
    Reject(f,sc::Reason::UnpublishedKey,"invalidated key rejected");
    f = good; ++f.taps[0].recall.capturedGeneration;
    Reject(f,sc::Reason::StaleKey,"overwritten physical slot generation rejected");
    f = good; f.taps[0].recall.frame = f.recipient.domain.frame;
    Reject(f,sc::Reason::StaleKey,"future or same-frame key cannot be recalled");
    f = good; f.taps[0].recall.slot = 6;
    Reject(f,sc::Reason::InvalidKeySlot,"unused native ring sentinel rejected");
    f = good; f.taps[0].recall.gridX = -.25;
    Reject(f,sc::Reason::UnavailableCorrespondence,"out-of-domain history is not edge-clamped into evidence");
    f = good; f.taps[0].recall.taps[0].weight = 0; f.taps[0].recall.taps[1].weight += .375;
    Reject(f,sc::Reason::InvalidWeight,"zeroing a real key tap cannot manufacture pure support");
    f = good; ++f.taps[0].recall.taps[0].cell.x;
    Reject(f,sc::Reason::WrongFootprint,"wrong original key sample origin rejected");
    f = good; ++f.taps[0].current.domain.cropX;
    Reject(f,sc::Reason::CropGridMismatch,"moving crop/grid phase mismatch rejected");
    f = good; f.globalVetoObserved = false;
    Reject(f,sc::Reason::UnobservedGlobalVeto,"unobserved frame veto remains explicit");
    f = good; ++f.taps[0].current.domain.frame;
    Reject(f,sc::Reason::StaleKey,"wrong current donor frame rejected");
    f = good; f.taps[0].current.policy.planeRelative = 1;
    Reject(f,sc::Reason::InvalidPolicy,"weaker cell certificate cannot bypass estimator policy");

    auto c = sc::Produce(good);
    d = Domain(); ++d.resetEpoch;
    Check(!sc::Accepts(c,d,3,7,7),"consumer rejects stale epoch");
    d = Domain(); ++d.frame;
    Check(!sc::Accepts(c,d,3,7,7),"consumer rejects stale frame");
    d = Domain(); d.cropX = 8; d.cropWidth = 120;
    Check(!sc::Accepts(c,d,3,7,7),"consumer rejects moved aligned crop");
    d = Domain(); d.cropX = 1; d.cropWidth = 127;
    Check(!sc::Accepts(c,d,3,7,7),"consumer rejects wrong grid phase");
    d = Domain(); d.cropX = -8;
    Check(sc::ValidateDomain(d) != 0,"negative crop origin rejected");
    d = Domain(); d.cropX = 24;
    Check(sc::ValidateDomain(d) != 0,"observed crop must fit full active render");
    d = Domain(); d.cropX = 64; d.cropWidth = 64;
    Check(!sc::CompleteObservedCell(d,7,7),"whole donor cell must be inside actual observed crop");
    auto outsideCrop = c; outsideCrop.domain = d;
    Check(!sc::Accepts(outsideCrop,d,3,7,7),"consumer rejects matching serialized crop that excludes recipient");
    Check(!sc::Accepts(c,Domain(),1,7,7),"consumer rejects wrong estimator radius");
    Check(!sc::Accepts(c,Domain(),3,8,7),"consumer rejects wrong recipient");
    c.observedTapMask &= ~1u;
    Check(!sc::Accepts(c,Domain(),3,7,7),"consumer rejects incomplete donor mask");
    c = sc::Produce(good); c.policy.planeRelative *= 100;
    Check(!sc::Accepts(c,Domain(),3,7,7),"consumer requires matching geometric tolerance");
    c = sc::Produce(good); c.scope = 0;
    Check(!sc::Accepts(c,Domain(),3,7,7),"consumer requires explicit support scope");
    const auto absent = sc::InvalidNativeSupport(7,20);
    Check(!absent.valid && absent.domain.resetEpoch == 7 && absent.domain.frame == 20 &&
          (absent.reasons&sc::Bits(sc::Reason::UnavailableDonorFootprint)) &&
          (absent.reasons&sc::Bits(sc::Reason::UnavailableKeyCorrespondence)),"native missing evidence emits reasoned invalid support");

    std::cout << "support_contract: " << checks << " checks, " << failures << " failures; mutant=" << mutant << '\n';
    return failures ? 1 : 0;
}
