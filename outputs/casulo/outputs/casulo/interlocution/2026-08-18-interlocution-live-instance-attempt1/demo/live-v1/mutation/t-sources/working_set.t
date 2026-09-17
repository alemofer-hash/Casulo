language T/2.0
module research.interlocution.working_set
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan e3c8959ba9187e6c5053eb50b14ed97071a409a061e66679990ecbfb934a1ebe

record WorkingSetObservation
  member available_records: Int
  member selection_supported: Bool
  member cancelled: Bool

fn decide(input: WorkingSetObservation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.available_records == 1024 else "working_set_records_unavailable"
  requires input.selection_supported else "working_set_selection_unavailable"
  return ok {'working_set_policy': 'all_records', 'working_set_start': '0', 'working_set_count': '1024'}
