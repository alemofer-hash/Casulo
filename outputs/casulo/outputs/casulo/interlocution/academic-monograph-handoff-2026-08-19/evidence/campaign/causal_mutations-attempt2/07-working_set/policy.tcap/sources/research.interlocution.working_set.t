language T/2.0
module research.interlocution.working_set
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 18bfc5d0d80fe52c347744ba7ca330653e7ba064ecba2f406efe63f05e8ded4e

record WorkingSetObservation
  member available_records: Int
  member selection_supported: Bool
  member cancelled: Bool

fn decide(input: WorkingSetObservation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.available_records == 1024 else "working_set_records_unavailable"
  requires input.selection_supported else "working_set_selection_unavailable"
  return ok {'working_set_policy': 'all_records', 'working_set_start': '0', 'working_set_count': '512'}
