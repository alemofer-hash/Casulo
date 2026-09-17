language T/2.0
module research.interlocution.initialization
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 18bfc5d0d80fe52c347744ba7ca330653e7ba064ecba2f406efe63f05e8ded4e

record InitializationObservation
  member observed_sha256: Text
  member cases_unique: Bool
  member nonces_unique: Bool
  member cancelled: Bool

fn decide(input: InitializationObservation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.observed_sha256 == '1b77bc6f3ee729282756b8244c4b198395e2fe6bcda6a8d4dd255aa370af13e3' else "initialization_hash_mismatch"
  requires input.cases_unique else "initialization_cases_not_unique"
  requires input.nonces_unique else "initialization_nonces_not_unique"
  return ok {'bundle_sha256': '1b77bc6f3ee729282756b8244c4b198395e2fe6bcda6a8d4dd255aa370af13e3', 'initialization_state_policy': 'reset_each_case'}
