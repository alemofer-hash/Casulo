language T/2.0
module research.interlocution.holdout.holdout_linear_mae_v1.dataset_identity_integrity
budget steps 4096
budget deadline_ms 5000
schema version 1
# holdout-spec 6fed658672c2f5d4bb709fef63c52a93491164f47fb04cbfb070c488bfd31260

record Observation
  member observed_sha256: Text
  member records: Int
  member input_features: Int
  member supported: Bool
  member cancelled: Bool

fn decide(input: Observation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.observed_sha256 == 'd8e8614078a7cae61ddac04db093c12346aac62c8a75a04fcc6cf5161b79a73e' else "dataset_hash_mismatch"
  requires input.records == 256 else "records_mismatch"
  requires input.input_features == 3 else "features_mismatch"
  requires input.supported else "primitive_unsupported"
  return ok {'dataset_sha256': 'd8e8614078a7cae61ddac04db093c12346aac62c8a75a04fcc6cf5161b79a73e', 'records': '256', 'input_features': '3'}
