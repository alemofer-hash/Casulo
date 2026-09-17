language T/2.0
module research.interlocution.holdout.holdout_logistic_bce_subset_v1.dataset_identity_integrity
budget steps 4096
budget deadline_ms 5000
schema version 1
# holdout-spec 83625e44cb4b25345cb879805749757aee6700e7034d9bbd0264a07308db9e7e

record Observation
  member observed_sha256: Text
  member records: Int
  member input_features: Int
  member supported: Bool
  member cancelled: Bool

fn decide(input: Observation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.observed_sha256 == '97675c3cdfe2be515108ef304f7043aaeca7e5897f6672365ec807b0a00912d6' else "dataset_hash_mismatch"
  requires input.records == 384 else "records_mismatch"
  requires input.input_features == 4 else "features_mismatch"
  requires input.supported else "primitive_unsupported"
  return ok {'dataset_sha256': '97675c3cdfe2be515108ef304f7043aaeca7e5897f6672365ec807b0a00912d6', 'records': '384', 'input_features': '4'}
