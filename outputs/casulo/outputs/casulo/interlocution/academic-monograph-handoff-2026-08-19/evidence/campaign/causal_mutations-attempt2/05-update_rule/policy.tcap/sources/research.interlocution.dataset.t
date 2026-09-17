language T/2.0
module research.interlocution.dataset
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 18bfc5d0d80fe52c347744ba7ca330653e7ba064ecba2f406efe63f05e8ded4e

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
