language T/2.0
module research.interlocution.optimizer_state
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 7516a0da239ef899d45532c839a87c906cb46b793061ac3a6d481bb002c9252a

record OptimizerStateCapabilities
  member reset_supported: Bool
  member no_cross_case_state: Bool
  member cancelled: Bool

fn decide(input: OptimizerStateCapabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.reset_supported else "optimizer_reset_unavailable"
  requires input.no_cross_case_state else "optimizer_state_contamination"
  return ok {'optimizer_state_policy': 'reset_each_case'}
