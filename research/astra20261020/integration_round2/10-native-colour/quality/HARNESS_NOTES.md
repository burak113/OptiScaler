# Harness corrections

Before running the new holdout, the first metrology unittest invocation ran
eight tests with one failure. `test_dose_matching_measures_stored_output_and_keeps_alpha`
requested dose 0.5 using the frozen generic `basic_scene` colour contrast. That
scene exceeds the candidate's frozen log-delta budget, so the matcher correctly
returned `matched=False`; the test had assumed an attainable dose.

The unit fixture was corrected to a modest, analytically specified source change
inside the existing delta budget. The matching target, tolerance, implementation,
protocol, candidate constants, original quality gates and heldout seeds were not
changed. The test still requests 0.5 and now checks the stored-output dose and
opaque-alpha protection. This was a test-fixture correction, not tuning after a
holdout result.
