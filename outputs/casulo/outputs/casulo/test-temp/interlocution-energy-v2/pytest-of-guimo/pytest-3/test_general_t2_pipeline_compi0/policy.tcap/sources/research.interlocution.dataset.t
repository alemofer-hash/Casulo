language T/2.0
module research.interlocution.dataset
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 7516a0da239ef899d45532c839a87c906cb46b793061ac3a6d481bb002c9252a

record DatasetObservation
  member observed_sha256: Text
  member records: Int
  member input_features: Int
  member cancelled: Bool

fn decide(input: DatasetObservation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.observed_sha256 == 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' else "dataset_hash_mismatch"
  requires input.records == 1024 else "dataset_record_count_mismatch"
  requires input.input_features == 8 else "dataset_feature_count_mismatch"
  return ok {'dataset_sha256': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'records': '1024', 'input_features': '8'}
