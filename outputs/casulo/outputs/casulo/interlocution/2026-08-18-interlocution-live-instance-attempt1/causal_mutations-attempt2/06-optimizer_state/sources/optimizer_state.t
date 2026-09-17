language T/2.0
module research.interlocution.optimizer_state
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 18bfc5d0d80fe52c347744ba7ca330653e7ba064ecba2f406efe63f05e8ded4e

record OptimizerStateCapabilities
  member reset_supported: Bool
  member no_cross_case_state: Bool
  member cancelled: Bool

fn decide(input: OptimizerStateCapabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.reset_supported else "optimizer_reset_unavailable"
  requires input.no_cross_case_state else "optimizer_state_contamination"
  return ok {'optimizer_state_policy': 'preserve_across_cases'}
