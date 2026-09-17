language T/2.0
module research.interlocution.dataset
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan e3c8959ba9187e6c5053eb50b14ed97071a409a061e66679990ecbfb934a1ebe

record DatasetObservation
  member observed_sha256: Text
  member records: Int
  member input_features: Int
  member cancelled: Bool

fn decide(input: DatasetObservation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.observed_sha256 == 'f393212f183a28a663adeb11995c5ab3ac769df7f06ded2dcfbc5e91cd31f802' else "dataset_hash_mismatch"
  requires input.records == 1024 else "dataset_record_count_mismatch"
  requires input.input_features == 8 else "dataset_feature_count_mismatch"
  return ok {'dataset_sha256': 'f393212f183a28a663adeb11995c5ab3ac769df7f06ded2dcfbc5e91cd31f802', 'records': '1024', 'input_features': '8'}
