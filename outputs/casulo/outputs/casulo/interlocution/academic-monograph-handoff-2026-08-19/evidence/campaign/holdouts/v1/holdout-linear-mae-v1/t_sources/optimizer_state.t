language T/2.0
module research.interlocution.holdout.holdout_linear_mae_v1.optimizer_state
budget steps 4096
budget deadline_ms 5000
schema version 1
# holdout-spec 6fed658672c2f5d4bb709fef63c52a93491164f47fb04cbfb070c488bfd31260

record Capabilities
  member supported: Bool
  member no_cross_case_state: Bool
  member cancelled: Bool

fn decide(input: Capabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.supported else "optimizer_state_unsupported"
  requires input.no_cross_case_state else "optimizer_state_contamination"
  return ok {'optimizer_state_policy': 'reset_each_case'}
