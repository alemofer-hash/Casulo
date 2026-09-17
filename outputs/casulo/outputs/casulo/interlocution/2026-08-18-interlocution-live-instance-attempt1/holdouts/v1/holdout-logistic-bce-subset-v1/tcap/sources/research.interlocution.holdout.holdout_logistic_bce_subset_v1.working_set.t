language T/2.0
module research.interlocution.holdout.holdout_logistic_bce_subset_v1.working_set
budget steps 4096
budget deadline_ms 5000
schema version 1
# holdout-spec 83625e44cb4b25345cb879805749757aee6700e7034d9bbd0264a07308db9e7e

record Observation
  member available_records: Int
  member supported: Bool
  member cancelled: Bool

fn decide(input: Observation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.available_records >= 256 else "working_set_unavailable"
  requires input.supported else "selection_unsupported"
  return ok {'working_set_policy': 'selected_range', 'working_set_start': '0', 'working_set_count': '256'}
