#include "../../fsrd_preprocess/RRTraceFenceState.h"
#include <iostream>
#include <stdexcept>
static unsigned checks=0;
static void check(bool pass,const char* name)
{
    ++checks;
    if (!pass) throw std::runtime_error(name);
}
int main() try
{
    using RRTraceFence::State;
    State normal; normal.recorded=true;
    check(!normal.Ready(100),"Elapsed frames cannot certify submission");
    check(normal.Submit(),"First submission");
    check(!normal.Ready(1)&&!normal.CanRelease(1),"Executable list remains owned");
    normal.ResetSucceeded();
    check(!normal.Ready(1)&&!normal.CanRelease(1),"Pending post-submission Signal retains storage");
    normal.SignalEnqueued(true);
    check(!normal.Ready(0)&&normal.Ready(1),"Fence completion required");
    check(normal.CanRelease(1)&&!normal.Submit(),"Reset detaches original generation");
    check(!normal.Ready(UINT64_MAX)&&!normal.CanRelease(UINT64_MAX),"Device removal cannot publish");
    State discarded; discarded.recorded=true; discarded.ResetSucceeded();
    check(discarded.invalid&&!discarded.Ready(100)&&discarded.CanRelease(0),"Discarded recording cannot publish");
    State duplicate; duplicate.recorded=true; duplicate.Submit(); duplicate.Submit();
    duplicate.ResetSucceeded(); duplicate.SignalEnqueued(true); duplicate.SignalEnqueued(true);
    check(!duplicate.Ready(2)&&!duplicate.CanRelease(2),"Repeated submission quarantines ambiguous resources");
    State failed; failed.recorded=true; failed.Submit(); failed.SignalEnqueued(false); failed.ResetSucceeded();
    check(!failed.Ready(2)&&!failed.CanRelease(2),"Failed Signal cannot be replaced by a token");
    State incomplete; incomplete.Submit(); incomplete.SignalEnqueued(true); incomplete.ResetSucceeded();
    check(!incomplete.Ready(1)&&incomplete.CanRelease(1),"Incomplete recording may retire, never publish");
    State snapshot; snapshot.recorded=true;
    check(!snapshot.CanSnapshot(100),"Snapshot requires an actual submission");
    snapshot.Submit();
    check(!snapshot.CanSnapshot(1),"Snapshot cannot race a pending post-submit signal");
    snapshot.SignalEnqueued(true);
    check(!snapshot.CanSnapshot(0)&&snapshot.CanSnapshot(1),"Guarded snapshot requires completed fence");
    check(!snapshot.Ready(1)&&!snapshot.CanWait()&&!snapshot.CanRelease(1),
        "Guarded snapshot never invents detach or releases an executable recording");
    check(!snapshot.CanSnapshot(UINT64_MAX),"Snapshot rejects device removal");
    check(!discarded.CanSnapshot(100)&&!failed.CanSnapshot(100)&&!incomplete.CanSnapshot(100),
        "Snapshot rejects discarded, failed and incomplete recordings");
    snapshot.Submit(); snapshot.SignalEnqueued(true);
    check(!snapshot.CanSnapshot(2),"Later resubmission forbids a second snapshot");
    snapshot.ResetSucceeded();
    check(!snapshot.CanRelease(2),"Snapshot never relaxes ambiguous-submission quarantine");
    State unvisited; unvisited.recorded=true; unvisited.Submit(); unvisited.SignalEnqueued(true);
    unvisited.UntrackedSubmission(); unvisited.ResetSucceeded();
    check(!unvisited.CanSnapshot(1)&&!unvisited.CanRelease(1),
        "Observer failure quarantines unvisited resubmission despite old completed fence and Reset");
    State unseen; unseen.recorded=true; unseen.UntrackedSubmission(); unseen.ResetSucceeded();
    check(!unseen.CanSnapshot(100)&&!unseen.CanRelease(100),
        "Observer failure cannot classify an unseen execution as an unsubmitted discard");
    std::cout<<"PASS "<<checks<<" fence lifecycle checks\n";
    return 0;
}
catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
