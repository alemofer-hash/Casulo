language T/2.0
module research.interlocution.holdout.holdout_linear_mae_v1.initialization_bundle
budget steps 4096
budget deadline_ms 5000
schema version 1
# holdout-spec 6fed658672c2f5d4bb709fef63c52a93491164f47fb04cbfb070c488bfd31260

record Observation
  member observed_sha256: Text
  member cases_unique: Bool
  member nonces_unique: Bool
  member supported: Bool
  member cancelled: Bool

fn decide(input: Observation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.observed_sha256 == '8a6d13f534bdd21b3770fa3c7e0dfed67a39b775972a51eee63feac54a0a03d6' else "initialization_hash_mismatch"
  requires input.cases_unique else "cases_not_unique"
  requires input.nonces_unique else "nonces_not_unique"
  requires input.supported else "primitive_unsupported"
  return ok {'bundle_sha256': '8a6d13f534bdd21b3770fa3c7e0dfed67a39b775972a51eee63feac54a0a03d6', 'initialization_state_policy': 'reset_each_case'}
