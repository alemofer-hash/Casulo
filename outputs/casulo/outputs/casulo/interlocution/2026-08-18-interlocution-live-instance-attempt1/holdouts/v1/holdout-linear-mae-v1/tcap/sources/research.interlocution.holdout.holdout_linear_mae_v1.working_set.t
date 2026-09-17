language T/2.0
module research.interlocution.holdout.holdout_linear_mae_v1.working_set
budget steps 4096
budget deadline_ms 5000
schema version 1
# holdout-spec 6fed658672c2f5d4bb709fef63c52a93491164f47fb04cbfb070c488bfd31260

record Observation
  member available_records: Int
  member supported: Bool
  member cancelled: Bool

fn decide(input: Observation) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.available_records >= 256 else "working_set_unavailable"
  requires input.supported else "selection_unsupported"
  return ok {'working_set_policy': 'selected_range', 'working_set_start': '0', 'working_set_count': '256'}
