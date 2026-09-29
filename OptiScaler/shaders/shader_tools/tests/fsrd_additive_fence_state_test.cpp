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
    std::cout<<"PASS "<<checks<<" fence lifecycle checks\n";
    return 0;
}
catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
