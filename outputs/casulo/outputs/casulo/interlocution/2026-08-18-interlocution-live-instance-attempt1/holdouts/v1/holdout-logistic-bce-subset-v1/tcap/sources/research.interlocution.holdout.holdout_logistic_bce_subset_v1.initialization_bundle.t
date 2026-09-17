language T/2.0
module research.interlocution.holdout.holdout_logistic_bce_subset_v1.initialization_bundle
budget steps 4096
budget deadline_ms 5000
schema version 1
# holdout-spec 83625e44cb4b25345cb879805749757aee6700e7034d9bbd0264a07308db9e7e

record Observation
  member observed_sha256: Text
  member cases_unique: Bool
  member nonces_unique: Bool
  member supported: Bool
  member cancelled: Bool

fn decide(input: Observation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.observed_sha256 == '954defff423abf4c720fce5766e26593ce3066c56f3114f5b24cf0c4e1094321' else "initialization_hash_mismatch"
  requires input.cases_unique else "cases_not_unique"
  requires input.nonces_unique else "nonces_not_unique"
  requires input.supported else "primitive_unsupported"
  return ok {'bundle_sha256': '954defff423abf4c720fce5766e26593ce3066c56f3114f5b24cf0c4e1094321', 'initialization_state_policy': 'reset_each_case'}
