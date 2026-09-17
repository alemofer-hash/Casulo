language T/2.0
module research.interlocution.working_set
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 7516a0da239ef899d45532c839a87c906cb46b793061ac3a6d481bb002c9252a

record WorkingSetObservation
  member available_records: Int
  member selection_supported: Bool
  member cancelled: Bool

fn decide(input: WorkingSetObservation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.available_records == 1024 else "working_set_records_unavailable"
  requires input.selection_supported else "working_set_selection_unavailable"
  return ok {'working_set_policy': 'all_records', 'working_set_start': '0', 'working_set_count': '1024'}
