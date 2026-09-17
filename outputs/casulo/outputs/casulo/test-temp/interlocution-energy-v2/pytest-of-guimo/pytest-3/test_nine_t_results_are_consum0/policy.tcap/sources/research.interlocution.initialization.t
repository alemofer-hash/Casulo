language T/2.0
module research.interlocution.initialization
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 7516a0da239ef899d45532c839a87c906cb46b793061ac3a6d481bb002c9252a

record InitializationObservation
  member observed_sha256: Text
  member cases_unique: Bool
  member nonces_unique: Bool
  member cancelled: Bool

fn decide(input: InitializationObservation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.observed_sha256 == 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' else "initialization_hash_mismatch"
  requires input.cases_unique else "initialization_cases_not_unique"
  requires input.nonces_unique else "initialization_nonces_not_unique"
  return ok {'bundle_sha256': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'initialization_state_policy': 'reset_each_case'}
