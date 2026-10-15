"""D09/WP01 diagnostics-only contract for the work_pipeline_profile gate.

CPU source-level proof. It pins the fail-closed admission structure and the new
sub-reason enrichment in production FSRDNrdBridge_Dx12.cpp without executing it:
the real native negative paths stay covered by the actual-host transaction,
submission-gate, indirect-proof and stencil tests this driver is run beside.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fsrd_nrd_root_restore import function

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp'


def production():
    return SOURCE.read_text(encoding='utf-8')


class WorkPipelineDiagnostics(unittest.TestCase):
    def test_gate_stays_fail_closed_and_splits_sub_reasons(self):
        text = production()
        body = function(text, 'bool PreserveNativeWork(')
        # Old single-condition form must be gone; every sub-reason still rejects.
        self.assertNotIn('if(!pipeline||selected.profile<0||selected.birth!=list.pipelineBirth)return reject("work_pipeline_profile");', body)
        for detail in ('pipeline_absent', 'profile_unclassified', 'pipeline_birth_changed'):
            self.assertIn('rejectDetail("work_pipeline_profile","%s")' % detail, body)
        self.assertEqual(body.count('return rejectDetail("work_pipeline_profile",'), 3)
        # Exactly two admissions: an empty pending set (nothing to preserve) and
        # the final fully-proven path. Every other exit is a reject lambda.
        self.assertEqual(body.count('return true'), 2, 'no unproven work may reach the end of the gate')
        self.assertIn('if(!count)return true;', body)
        self.assertIn('const auto rejectDetail=[](const char* gate,const char* detail){gNativeWorkFailure=gate;gNativeWorkDetail=detail;return false;};', body)

    def test_detail_is_diagnostic_only(self):
        text = production()
        body = function(text, 'bool PreserveNativeWork(')
        # The detail is written next to the gate and reset per call; it never
        # influences a branch: no read outside the invalidation log.
        self.assertIn('gNativeWorkFailure="unclassified_work";gNativeWorkDetail=nullptr;', body)
        self.assertNotIn('gNativeWorkDetail', function(text, 'void InvalidateRecordingProof(').split('if(pending)')[0])
        self.assertIn('const char* detail=gNativeWorkDetail;gNativeWorkDetail=nullptr;', text)

    def test_identity_record_is_verified_not_synthesized(self):
        text = production()
        log = function(text, 'void InvalidateRecordingProof(')
        self.assertIn('const bool identityRecorded=FrameSurvey::ResolvePipelineShaderIdentity(pipeline,identity);', log)
        self.assertIn('known_compute_profile={}', log)
        self.assertIn('known_graphics_profile={}', log)
        self.assertIn('subreason={}', log)
        self.assertIn('identity_recorded={}', log)
        # No whitelist extension and no hash substitution: the known-profile
        # lookup stays a pure read of the existing lists.
        self.assertIn('const int knownComputeProfile=identityRecorded&&identity.presentStages==FrameSurvey::PipelineCS?', log)
        self.assertNotIn('interveningPipelines[pipeline]=', log)

    def test_unknown_compute_still_has_no_admission_path(self):
        text = production()
        body = function(text, 'bool PreserveNativeWork(')
        # Unknown compute/profile can only leave through the reject lambdas; the
        # known-hash checks below still gate every admission.
        self.assertIn('else if(selected.profile>1||InterveningComputeProfile(identity.compute.data())!=selected.profile)return reject("work_compute_hash");', body)
        self.assertIn('if(selected.profile<2||selected.profile>4||std::string_view(identity.pixel.data())!=NativeInterveningPS[selected.profile-2]', body)
        self.assertIn('!identity.complete||identity.pipelineBirth!=selected.birth)return reject("work_pipeline_identity_or_predication");', body)

    def test_plain_indirect_entry_still_clears_detail(self):
        text = production()
        body = function(text, 'bool PreserveIndirectRecording(')
        self.assertIn('gNativeWorkFailure="work_indirect_signature_or_state";gNativeWorkDetail=nullptr;', body)


if __name__ == '__main__':
    unittest.main()
