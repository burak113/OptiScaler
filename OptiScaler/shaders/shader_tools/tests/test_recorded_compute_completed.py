"""Preserve the full Poll suite and add exactly-once unlocked completion callbacks."""
import test_recorded_compute_poll as base

ADDED = r'''
void completedCallbacks(){
 std::atomic<unsigned> calls{0};std::atomic<bool> alive{false};std::weak_ptr<Owner> weak;
 L::SubmissionCallbacks callbacks;
 callbacks.completed=[&](const auto& info){
  need(registryFree(),"completion callback is outside Registry mutex");
  need(info.submissionId&&info.recordingId&&!info.snapshotFallback,"completion retains exact submission identity");
  alive=!weak.expired();++calls;
 };
 need(!callbacks.Empty(),"completion-only callback is a retained participant");
 {
  Environment e(callbacks);auto s=e.before();L::AfterSubmission(s);weak=e.lease;
  checkedPoll();need(calls==0,"incomplete fence never calls completed");
  auto* fence=static_cast<FakeFence*>(s->fence.Get());fence->completed=1;Pause pause;fence->pause=&pause;
  e.detach();e.lease.reset();s.reset();
  std::thread a([&]{ProbeScope guard(false);L::Poll();}),b([&]{ProbeScope guard(false);L::Poll();});
  const bool entered=pause.wait(2);pause.release();a.join();b.join();
  need(entered&&calls==1&&alive,"concurrent snapshots notify exactly once while lease remains pinned");
  need(weak.expired()&&L::GetRegistry().submissions.empty(),"completion callback has no ownership cycle");
  checkedPoll();need(calls==1,"retired submission never notifies twice");
 }
 callbacks={};callbacks.completed=[](const auto&){need(registryFree(),"throwing callback is unlocked");throw 17;};
 {
  Environment e(callbacks);e.queue->completeSignal=true;auto s=e.before();L::AfterSubmission(s);
  {ProbeScope guard(true,false);L::Poll();}
  need(FAILED(L::RequiredSubmissionFailure())&&!L::Available(),"completion exception latches required submission failure");
  need(s->registrySlot==L::Submission::Unregistered&&L::GetRegistry().submissions.empty(),"throwing callback cannot strand completed owner");
 }
 // CPU-only fixture reset AFTER all callback/submission/recording owners drained.
 // Production has no mechanism to clear its mandatory failure latch.
 L::gUntrackedRequiredSubmissionFailure.store(S_OK);
 need(!nativeInside&&!ownedInside&&!memoryInside,"completion callback and failures keep native/owner work outside Registry lock");
}
'''


if __name__ == '__main__':
    assert base.TESTS.count('int main()try{') == 1
    assert base.TESTS.count('participantsAndReset();') == 1
    base.TESTS = base.TESTS.replace('int main()try{', ADDED+'\nint main()try{')
    base.TESTS = base.TESTS.replace('participantsAndReset();', 'participantsAndReset();completedCallbacks();')
    base.run()
