"""Actual bounded material-state witness and Birth metadata, CPU only.

Uses the real Windows SDK barrier/BoundResource types and production headers.
Resource pointers are deliberately non-dereferenceable addresses; no COM/native
device, physical detour, queue, shader, GPU or game-state proof is claimed.
Each scenario runs in a fresh process. --prepare-only writes source and hashes
without finding a compiler or executing native code.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
CASES = [
    "unknown", "whole", "subresource-zero", "other-subresource", "pixel-only",
    "common", "read-combinations", "writable", "one-target", "serial",
    "reset-early", "split-match", "split-unpaired", "split-mismatch",
    "split-serial", "alias-endpoints", "alias-wildcard", "uav", "other-resource",
    "same-selection", "changed-selection", "birth-live", "birth-invalid",
    "ping-pong-two", "ping-pong-four", "ring-eviction", "allocation-free", "duplicate-target",
    "legacy-generation", "legacy-zero-generation",
    "known-states", "known-invalid", "seed-new-list", "seed-selection", "seed-ring",
    "seed-generation", "seed-birth", "seed-allocation-free", "supported-states",
]

CPP = r'''
#define NOMINMAX
#include <windows.h>
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdNativeMaterialStateWitness.h"
#include <array>
#include <atomic>
#include <cstdlib>
#include <iostream>
#include <new>
#include <stdexcept>
#include <string>

__CAPTURE_POLICY__
using Witness = NrdBridge::NativeMaterialStateWitness;
using IdentityCache = NrdBridge::NativeMaterialIdentityCache;
using Bound = FrameSurvey::BoundResource;
using Token = NrdBridgeBirth::Token;
unsigned checks = 0;
thread_local bool meter = false;
std::atomic<unsigned> allocations = 0;
void* operator new(size_t size)
{ if(meter)++allocations; if(auto* p=std::malloc(size?size:1))return p; throw std::bad_alloc(); }
void* operator new[](size_t size) { return ::operator new(size); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
void operator delete[](void* p, size_t) noexcept { std::free(p); }
void need(bool value,const char* message)
{ if(!value)throw std::runtime_error(message); ++checks; }

struct Pair { Bound base,params; };
Pair pair(unsigned index=0)
{
    Pair result;
    result.base.resource=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x100000)+index*0x2000);
    result.params.resource=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x101000)+index*0x2000);
    result.base.resourceGeneration=1000+index*2;
    result.params.resourceGeneration=1001+index*2;
    return result;
}
constexpr auto readState=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
D3D12_RESOURCE_BARRIER transition(ID3D12Resource* resource,
    D3D12_RESOURCE_STATES after=readState,
    D3D12_RESOURCE_BARRIER_FLAGS flags=D3D12_RESOURCE_BARRIER_FLAG_NONE,
    UINT subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
    D3D12_RESOURCE_STATES before=D3D12_RESOURCE_STATE_RENDER_TARGET)
{
    D3D12_RESOURCE_BARRIER result{};
    result.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION; result.Flags=flags;
    result.Transition={resource,subresource,before,after}; return result;
}
void observe(Witness& w,const Pair& p,uint64_t serial=1,
    D3D12_RESOURCE_STATES after=readState,
    D3D12_RESOURCE_BARRIER_FLAGS flags=D3D12_RESOURCE_BARRIER_FLAG_NONE,
    UINT subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
    D3D12_RESOURCE_STATES before=D3D12_RESOURCE_STATE_RENDER_TARGET)
{
    const std::array barriers{transition(p.base.resource,after,flags,subresource,before),
                              transition(p.params.resource,after,flags,subresource,before)};
    w.Observe(UINT(barriers.size()),barriers.data(),serial);
}
void select(Witness& w,const Pair& p) { w.Select(p.base,p.params); }
void prove(Witness& w,const Pair& p,uint64_t serial=1)
{ select(w,p); observe(w,p,serial); need(w.Readable(serial),"selected pair has fresh native transition evidence"); }
void alias(Witness& w,ID3D12Resource* before,ID3D12Resource* after,uint64_t serial=1)
{
    D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_ALIASING;
    b.Aliasing={before,after};w.Observe(1,&b,serial);
}
bool metadata(void*,const Token&) noexcept { return true; }
Token birth(NrdBridgeBirth::Registry& registry,ID3D12Resource* resource,
            uint64_t stamp,bool initializing=false)
{
    auto token=registry.ObserveInstance(resource,stamp,metadata,metadata,nullptr,true,initializing);
    need(bool(token),"actual Birth registry published exact CPU metadata identity"); return token;
}

void run(const std::string& mode)
{
    Witness w;const auto p=pair();
    if(mode=="unknown")
    {
        need(!w.Readable(0),"unselected state unknown at serial zero");select(w,p);
        need(!w.Readable(1),"SRV binding alone does not prove state");w.Observe(0,nullptr,1);
        need(!w.Readable(1),"empty barrier span does not create proof");
    }
    else if(mode=="whole") { prove(w,p); }
    else if(mode=="subresource-zero")
    {select(w,p);observe(w,p,1,readState,D3D12_RESOURCE_BARRIER_FLAG_NONE,0);need(w.Readable(1),"subresource zero proves selected material view");}
    else if(mode=="other-subresource")
    {
        select(w,p);observe(w,p,1,readState,D3D12_RESOURCE_BARRIER_FLAG_NONE,1);
        need(!w.Readable(1),"subresource one cannot prove zero");
        auto unsupported=p;unsupported.base.subresource=1;select(w,unsupported);observe(w,p);
        need(!w.Readable(1),"nonzero selected material subresource is unsupported");
    }
    else if(mode=="pixel-only")
    {select(w,p);observe(w,p,1,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);need(!w.Readable(1),"pixel-only SRV is not compute-readable");}
    else if(mode=="common")
    {select(w,p);observe(w,p,1,D3D12_RESOURCE_STATE_COMMON);need(!w.Readable(1),"COMMON is never guessed to promote for optional material read");}
    else if(mode=="read-combinations")
    {
        select(w,p);observe(w,p,1,D3D12_RESOURCE_STATE_GENERIC_READ);
        need(w.Readable(1),"GENERIC_READ includes compute SRV");
        observe(w,p,1,D3D12_RESOURCE_STATES(readState|D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_DEPTH_READ));
        need(w.Readable(1),"combined read-only states retain compute eligibility");
    }
    else if(mode=="writable")
    {
        const std::array states{D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
            D3D12_RESOURCE_STATE_DEPTH_WRITE,D3D12_RESOURCE_STATE_STREAM_OUT,D3D12_RESOURCE_STATE_COPY_DEST,
            D3D12_RESOURCE_STATE_RESOLVE_DEST,D3D12_RESOURCE_STATE_VIDEO_DECODE_WRITE,
            D3D12_RESOURCE_STATE_VIDEO_PROCESS_WRITE,D3D12_RESOURCE_STATE_VIDEO_ENCODE_WRITE};
        select(w,p);for(auto state:states){observe(w,p,1,D3D12_RESOURCE_STATES(readState|state));
            need(!w.Readable(1),"every writable bit rejects even combined compute SRV state");}
    }
    else if(mode=="one-target")
    {
        select(w,p);auto b=transition(p.base.resource);w.Observe(1,&b,1);
        need(!w.Readable(1),"both exact material sources need proof");
        b=transition(p.params.resource);w.Observe(1,&b,1);need(w.Readable(1),"independent target proofs compose");
        auto missing=p;missing.params.resource=nullptr;select(w,missing);observe(w,p);
        need(!w.Readable(1),"null source never passes");
    }
    else if(mode=="serial")
    {
        prove(w,p);need(!w.Readable(2),"old cancellation serial rejected");
        auto b=transition(p.base.resource);w.Observe(1,&b,2);
        need(!w.Readable(2),"one updated target cannot combine across serials");
        b=transition(p.params.resource);w.Observe(1,&b,2);need(w.Readable(2),"both current-serial proofs accepted");
    }
    else if(mode=="reset-early")
    {
        prove(w,p);w.Invalidate();need(!w.Readable(1),"Reset invalidates even unchanged serial");
        observe(w,p,2);select(w,p);need(w.Readable(2),"retained pair sees next recording early barriers before Select");
        w.Observe(1,nullptr,2);need(!w.Readable(2),"malformed nonempty barrier span fails closed");
    }
    else if(mode=="split-match")
    {
        prove(w,p);observe(w,p,1,readState,D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY);
        need(!w.Readable(1),"BEGIN_ONLY clears readable state");
        observe(w,p,1,readState,D3D12_RESOURCE_BARRIER_FLAG_END_ONLY);
        need(w.Readable(1),"matching END_ONLY restores known state");
    }
    else if(mode=="split-unpaired")
    {
        select(w,p);observe(w,p,1,readState,D3D12_RESOURCE_BARRIER_FLAG_END_ONLY);
        need(!w.Readable(1),"unmatched split end does not prove");
        observe(w,p,1,readState,D3D12_RESOURCE_BARRIER_FLAGS(3));
        need(!w.Readable(1),"invalid combined split flags fail closed");
    }
    else if(mode=="split-mismatch")
    {
        select(w,p);
        for(unsigned change=0;change!=3;++change)
        {
            w.Invalidate();observe(w,p,1,readState,D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY);
            observe(w,p,1,change==0?D3D12_RESOURCE_STATE_GENERIC_READ:readState,
                D3D12_RESOURCE_BARRIER_FLAG_END_ONLY,change==1?0:D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                change==2?D3D12_RESOURCE_STATE_COMMON:D3D12_RESOURCE_STATE_RENDER_TARGET);
            need(!w.Readable(1),"split after/before/subresource must each match exactly");
        }
        w.Invalidate();observe(w,p,1,readState,D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY);observe(w,p);
        need(!w.Readable(1),"ordinary transition cannot silently finish a pending split");
    }
    else if(mode=="split-serial")
    {
        select(w,p);observe(w,p,1,readState,D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY);
        observe(w,p,2,readState,D3D12_RESOURCE_BARRIER_FLAG_END_ONLY);
        need(!w.Readable(2),"split halves across recording serial cannot pair");
    }
    else if(mode=="alias-endpoints")
    {
        const auto other=pair(10);prove(w,p);alias(w,p.base.resource,other.base.resource);
        need(!w.Readable(1),"alias before resource invalidates");observe(w,p);
        alias(w,other.base.resource,p.params.resource);need(!w.Readable(1),"alias after resource invalidates");
        observe(w,p);alias(w,other.base.resource,other.params.resource);
        need(w.Readable(1),"unrelated exact alias endpoints do not erase proof");
    }
    else if(mode=="alias-wildcard")
    {
        prove(w,p);alias(w,nullptr,pair(10).base.resource);
        need(!w.Readable(1),"null alias before is conservative wildcard");
        observe(w,p);alias(w,pair(10).base.resource,nullptr);
        need(!w.Readable(1),"null alias after is conservative wildcard");
    }
    else if(mode=="uav")
    {
        select(w,p);D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;b.UAV.pResource=p.base.resource;
        w.Observe(1,&b,1);need(!w.Readable(1),"UAV ordering is not state proof");
        observe(w,p);w.Observe(1,&b,1);need(w.Readable(1),"UAV ordering does not itself transition known state");
    }
    else if(mode=="other-resource")
    {select(w,p);observe(w,pair(10));need(!w.Readable(1),"unselected resources cannot supply proof");}
    else if(mode=="same-selection")
    {prove(w,p);for(unsigned i=0;i!=100;++i)select(w,p);need(w.Readable(1),"same exact pair preserves evidence");}
    else if(mode=="changed-selection")
    {
        prove(w,p);const auto q=pair(1);select(w,q);need(!w.Readable(1),"new identity pair starts unknown");
        select(w,p);need(w.Readable(1),"previous retained exact pair keeps its proof");
    }
    else if(mode=="birth-live")
    {
        NrdBridgeBirth::Registry registry;auto tracked=p;
        tracked.base.resourceBirth=birth(registry,p.base.resource,101);
        tracked.params.resourceBirth=birth(registry,p.params.resource,102);prove(w,tracked);
        need(registry.RetireCurrentInstance(tracked.base.resourceBirth,metadata,nullptr),"actual exact Birth retirement succeeds");
        need(!w.Readable(1),"retired weak target cannot remain readable");
        tracked.base.resourceBirth=birth(registry,p.base.resource,103);select(w,tracked);
        need(!w.Readable(1),"recycled same address new Birth does not inherit state");observe(w,tracked);
        need(w.Readable(1),"fresh recycled identity requires new transitions");
    }
    else if(mode=="birth-invalid")
    {
        NrdBridgeBirth::Registry registry;auto tracked=p;
        const auto wrong=birth(registry,pair(2).base.resource,201);tracked.base.resourceBirth=wrong;
        select(w,tracked);observe(w,tracked);need(!w.Readable(1),"Birth address mismatch is rejected");
        tracked.base.resourceBirth=birth(registry,p.base.resource,202,true);
        tracked.params.resourceBirth=birth(registry,p.params.resource,203);select(w,tracked);observe(w,tracked);
        need(!w.Readable(1),"pending initialized Birth is rejected");
        need(registry.Finalize(tracked.base.resourceBirth,true),"actual pending Birth finalized");
        need(!w.Readable(1),"finalization does not manufacture state proof");observe(w,tracked);need(w.Readable(1),"ready Birth plus fresh barriers accepted");
        {NrdBridgeBirth::ScopedRelease pending(tracked.base.resourceBirth);need(!w.Readable(1),"physical Release in flight rejects borrowed source");
            observe(w,tracked);need(!w.Readable(1),"transition during unadmitted Release does not publish proof");}
        need(!w.Readable(1),"ending Release does not manufacture missed state proof");observe(w,tracked);
        need(w.Readable(1),"fresh admitted transitions restore proof");registry.Fail();
        need(!w.Readable(1),"metadata health failure rejects formerly known weak targets");
    }
    else if(mode=="ping-pong-two"||mode=="ping-pong-four")
    {
        const unsigned count=mode=="ping-pong-two"?2:4;
        for(unsigned i=0;i!=count;++i)select(w,pair(i));
        for(uint64_t serial=1;serial!=5;++serial)
        {
            w.Invalidate();
            for(unsigned i=0;i!=count;++i)observe(w,pair(i),serial);
            for(unsigned i=0;i!=count;++i){select(w,pair(i));need(w.Readable(serial),"all cached alternating pairs receive early barriers before selection");}
        }
    }
    else if(mode=="ring-eviction")
    {
        for(unsigned i=0;i!=4;++i){select(w,pair(i));observe(w,pair(i));}
        select(w,pair(4));need(!w.Readable(1),"fifth pair starts unknown");
        observe(w,pair(0));select(w,pair(0));
        need(!w.Readable(1),"evicted oldest pair cannot recover proof from barriers while unselected");
        observe(w,pair(0));need(w.Readable(1),"reinserted evicted pair needs new observed transitions");
    }
    else if(mode=="legacy-generation")
    {
        prove(w,p);auto recycled=p;++recycled.base.resourceGeneration;
        select(w,recycled);need(!w.Readable(1),"same raw address with new legacy generation cannot inherit old state");
        observe(w,recycled);need(w.Readable(1),"new legacy generation needs fresh observed transitions");
        ++recycled.params.resourceGeneration;select(w,recycled);
        need(!w.Readable(1),"either material generation change invalidates current pair proof");
    }
    else if(mode=="legacy-zero-generation")
    {
        auto unknown=p;unknown.base.resourceGeneration=0;select(w,unknown);observe(w,unknown);
        need(!w.Readable(1),"unstamped legacy resource with unknown generation remains fallback-only");
        NrdBridgeBirth::Registry registry;auto tracked=p;
        tracked.base.resourceBirth=birth(registry,p.base.resource,301);
        tracked.params.resourceBirth=birth(registry,p.params.resource,302);
        tracked.base.resourceGeneration=tracked.params.resourceGeneration=0;prove(w,tracked);
        need(w.Readable(1),"exact admissible Birth identities do not require optional legacy generations");
    }
    else if(mode=="duplicate-target")
    {
        auto shared=p;shared.params=shared.base;select(w,shared);
        auto b=transition(shared.base.resource);w.Observe(1,&b,1);
        need(w.Readable(1),"two slots sharing one target follow one transition without duplicate native work");
        b=transition(shared.base.resource,readState,D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY);w.Observe(1,&b,1);
        need(!w.Readable(1),"one shared-target split begin invalidates both slots");
        b=transition(shared.base.resource,readState,D3D12_RESOURCE_BARRIER_FLAG_END_ONLY);w.Observe(1,&b,1);
        need(w.Readable(1),"one shared-target matching split end completes both independent proofs");
        alias(w,shared.base.resource,pair(10).base.resource);
        need(!w.Readable(1),"shared-target alias invalidates every matching slot");
    }
    else if(mode=="allocation-free")
    {
        for(unsigned i=0;i!=4;++i)select(w,pair(i));
        allocations=0;meter=true;bool valid=true;
        for(uint64_t serial=1;serial!=1001;++serial)
        {
            w.Invalidate();for(unsigned i=0;i!=4;++i)observe(w,pair(i),serial);
            for(unsigned i=0;i!=4;++i){select(w,pair(i));valid=valid&&w.Readable(serial);}
        }
        meter=false;need(valid,"1000 recording resets retain all four alternating pair identities");
        need(allocations==0,"bounded warmed Select/Observe/Readable/Invalidate allocate zero times");
    }
    else if(mode=="known-states")
    {
        Witness::SourceStates states{D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COPY_SOURCE};
        const auto unchanged=states;
        need(!w.TryKnownStates(1,states) && states==unchanged,"unknown output is untouched");
        select(w,p);
        for(const auto state : {readState,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,
                D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_UNORDERED_ACCESS})
        {
            observe(w,p,1,state);need(w.TryKnownStates(1,states),"exact known state is independent of compute-read eligibility");
            need(states[0]==state && states[1]==state,"both exact native states returned without promotion inference");
            need(w.Readable(1)==(state==readState),"legacy Readable policy remains unchanged");
        }
        auto b=transition(p.base.resource,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);w.Observe(1,&b,1);
        need(w.TryKnownStates(1,states) && states[0]==D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE &&
             states[1]==D3D12_RESOURCE_STATE_UNORDERED_ACCESS,"independent per-source state masks preserved");
    }
    else if(mode=="known-invalid")
    {
        Witness::SourceStates states{D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COPY_SOURCE};
        const auto unchanged=states;select(w,p);observe(w,p);
        need(!w.TryKnownStates(2,states) && states==unchanged,"known states do not cross cancellation serials");
        auto b=transition(p.base.resource,readState,D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY);w.Observe(1,&b,1);
        need(!w.TryKnownStates(1,states) && states==unchanged,"pending split cannot supply a transition-before state");
        observe(w,p);need(!w.TryKnownStates(1,states),"ordinary barrier cannot repair pending split implicitly");
        observe(w,p);need(w.TryKnownStates(1,states),"later independent full barriers reestablish proof");
        alias(w,nullptr,pair(20).base.resource);need(!w.TryKnownStates(1,states),"wildcard alias destroys exact-state proof");
        observe(w,p);w.Invalidate();need(!w.TryKnownStates(1,states),"Reset cannot carry known states");
    }
    else if(mode=="seed-new-list")
    {
        IdentityCache identities;need(identities.Empty(),"service cache starts empty");
        identities.Remember(p.base,p.params);need(!identities.Empty(),"first writer learns only weak identities");
        identities.Seed(w);Witness::SourceStates states{};
        need(!w.TryKnownStates(1,states),"seeding does not select or import a state");
        observe(w,p,1,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);select(w,p);
        need(w.TryKnownStates(1,states) && states[0]==D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,
             "fresh command list observes barriers before its first writer selection");
        Witness other;identities.Seed(other);select(other,p);
        need(!other.TryKnownStates(1,states),"another list cannot inherit known state from service identities");
        observe(other,p,2);need(other.TryKnownStates(2,states),"other list needs its own fresh barrier evidence");
        other.Invalidate();identities.Seed(other);select(other,p);
        need(!other.TryKnownStates(2,states),"close/reset plus reseeding does not revive old evidence");
    }
    else if(mode=="seed-selection")
    {
        prove(w,p);const auto q=pair(1);w.Seed(q.base,q.params);
        need(w.Readable(1),"seeding another identity preserves exact active selection");
        w.Seed(p.base,p.params);need(w.Readable(1),"reseeding existing pair preserves its current-recording proof");
        for(unsigned i=2;i!=5;++i){const auto q=pair(i);w.Seed(q.base,q.params);}
        Witness::SourceStates states{};
        need(!w.TryKnownStates(1,states),"evicting selection cannot select the replacement identity");
    }
    else if(mode=="seed-ring")
    {
        IdentityCache identities;for(unsigned i=0;i!=5;++i){const auto q=pair(i);identities.Remember(q.base,q.params);}
        identities.Seed(w);for(unsigned i=0;i!=5;++i)observe(w,pair(i));
        for(unsigned i=1;i!=5;++i){select(w,pair(i));need(w.Readable(1),"latest four service identities see early barriers");}
        select(w,p);need(!w.Readable(1),"fifth pair evicts old identity without fabricating missed state");
    }
    else if(mode=="seed-generation")
    {
        IdentityCache identities;identities.Remember(p.base,p.params);identities.Seed(w);observe(w,p);
        auto recycled=p;recycled.base.resourceGeneration+=100;recycled.params.resourceGeneration+=100;
        select(w,recycled);Witness::SourceStates states{};
        need(!w.TryKnownStates(1,states),"new legacy generation cannot consume seeded old-identity proof");
        identities.Remember(recycled.base,recycled.params);Witness next;identities.Seed(next);
        select(next,recycled);need(!next.TryKnownStates(1,states),"remembering new generation is not state evidence");
        observe(next,recycled);need(next.TryKnownStates(1,states),"new generation receives its own current recording barriers");
    }
    else if(mode=="seed-birth")
    {
        NrdBridgeBirth::Registry registry;auto tracked=p;
        tracked.base.resourceBirth=birth(registry,p.base.resource,301);
        tracked.params.resourceBirth=birth(registry,p.params.resource,302);
        IdentityCache identities;identities.Remember(tracked.base,tracked.params);identities.Seed(w);
        observe(w,tracked);select(w,tracked);Witness::SourceStates states{};
        need(w.TryKnownStates(1,states),"exact live Birth pair receives seeded recording-local proof");
        need(registry.RetireCurrentInstance(tracked.base.resourceBirth,metadata,nullptr),"old physical identity retired");
        auto recycled=tracked;recycled.base.resourceBirth=birth(registry,p.base.resource,401);
        identities.Remember(recycled.base,recycled.params);identities.Seed(w);select(w,recycled);
        need(!w.TryKnownStates(1,states),"recycled Birth cannot consume old state despite same address");
        observe(w,recycled);need(w.TryKnownStates(1,states),"recycled Birth needs new observed barriers");
    }
    else if(mode=="seed-allocation-free")
    {
        IdentityCache identities;for(unsigned i=0;i!=4;++i){const auto q=pair(i);identities.Remember(q.base,q.params);}
        allocations=0;meter=true;bool valid=true;Witness::SourceStates states{};
        for(uint64_t serial=1;serial!=1001;++serial)
        {
            Witness fresh;identities.Seed(fresh);
            for(unsigned i=0;i!=4;++i)observe(fresh,pair(i),serial,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
            for(unsigned i=0;i!=4;++i){const auto q=pair(i);identities.Remember(q.base,q.params);
                identities.Seed(fresh);select(fresh,q);valid=valid&&fresh.TryKnownStates(serial,states);}
        }
        meter=false;need(valid,"1000 fresh lists prove four seeded pairs only through their own barriers");
        need(allocations==0,"bounded service identity cache and fresh-list seeding allocate zero times");
    }
    else if(mode=="supported-states")
    {
        using P=CapturePolicy;using S=P::SourceStates;
        for(const auto state : {D3D12_RESOURCE_STATE_COMMON,readState,D3D12_RESOURCE_STATE_UNORDERED_ACCESS})
        {need(P::CanCaptureStates(S{state,readState},D3D12_COMMAND_LIST_TYPE_DIRECT),"known supported direct source state");
         need(P::CanCaptureStates(S{readState,state},D3D12_COMMAND_LIST_TYPE_COMPUTE),"known supported compute source state");}
        for(const auto state : {D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_GENERIC_READ,
                D3D12_RESOURCE_STATES(readState|D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE)})
        {need(P::CanCaptureStates(S{state,readState},D3D12_COMMAND_LIST_TYPE_DIRECT),"direct list supports exact pixel-read state");
         need(!P::CanCaptureStates(S{readState,state},D3D12_COMMAND_LIST_TYPE_COMPUTE),"compute list cannot restore pixel-state masks");}
        for(const auto state : {D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_DEPTH_WRITE,
                D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COPY_SOURCE,
                D3D12_RESOURCE_STATE_RESOLVE_DEST,D3D12_RESOURCE_STATES(readState|D3D12_RESOURCE_STATE_UNORDERED_ACCESS),
                D3D12_RESOURCE_STATES(0x80000000u)})
            need(!P::CanCaptureStates(S{state,readState},D3D12_COMMAND_LIST_TYPE_DIRECT),"unsupported or malformed exact states fail closed");
        for(const auto type : {D3D12_COMMAND_LIST_TYPE_BUNDLE,D3D12_COMMAND_LIST_TYPE_COPY})
            need(!P::CanCaptureStates(S{readState,readState},type),"non-dispatch command list cannot capture");
    }
    else throw std::runtime_error("unknown fixture case");
}
int main(int argc,char** argv)try
{
    SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
    const std::string mode=argc>1?argv[1]:"unknown";run(mode);
    std::cout<<"{\"case\":\""<<mode<<"\",\"checks\":"<<checks
             <<",\"allocations\":"<<allocations<<",\"native_calls\":0,\"gpu_submissions\":0}\n";
    return 0;
}
catch(const std::exception& error){std::cerr<<error.what()<<"\n";return 1;}
'''


def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    source = out / "nrd_material_state.cpp"
    capture = ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdNativeMaterialCapture_Dx12.h"
    text = capture.read_text()
    signature = "    static bool CanCaptureStates("
    assert text.count(signature) == 1, "one actual capture admission function"
    start = text.index(signature)
    opening = text.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    policy = ("class CapturePolicy { public: using SourceStates=std::array<D3D12_RESOURCE_STATES,2>;\n" +
              text[start:end] + "\n};")
    source.write_text(CPP.replace("__ROOT__", ROOT.as_posix()).replace("__CAPTURE_POLICY__", policy), encoding="utf-8")
    production = Path(os.environ.get("FSRD_NRD_PRODUCTION_ROOT", ROOT)).resolve()
    paths = [ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdNativeMaterialStateWitness.h", capture,
             production / "OptiScaler/misc/NrdBridgeBirth_Dx12.h",
             production / "OptiScaler/resource_tracking/FrameSurvey_Dx12.h"]
    assert "uint64_t resourceGeneration" in paths[-1].read_text(), "actual production BoundResource generation field required"
    contract = {"scope": __doc__, "cases": CASES,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "headers": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
                "production_root": str(production), "pair_capacity": 4, "weak_target_capacity": 8, "native_device": False,
                "real_com": False, "gpu_submissions": 0}
    (out / "contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    return source, contract


def main():
    out = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", ROOT / "nrd_material_state_output"))
    source, contract = generate(out)
    if "--prepare-only" in sys.argv:
        print(json.dumps({"source": str(source), "cases": len(CASES), "compiled": False, "executed": False}))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fsrd_toolchain import compile_cpp
    exe = out / "nrd_material_state.exe"
    production = Path(contract["production_root"])
    build = compile_cpp(source, exe, (), (production / "OptiScaler", ROOT / "OptiScaler"))
    (out / "build.json").write_text(json.dumps(build, indent=2), encoding="utf-8")
    results = []
    for case in CASES:
        result = subprocess.run([str(exe), case], capture_output=True, text=True, timeout=20)
        (out / (case + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        result.check_returncode()
        values = json.loads(result.stdout)
        assert values["native_calls"] == 0 and values["gpu_submissions"] == 0
        results.append(values)
    report = {"scope": contract["scope"], "checks": sum(row["checks"] for row in results), "cases": results}
    (out / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
