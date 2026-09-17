language T/2.0
module research.interlocution.optimizer_state
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan e3c8959ba9187e6c5053eb50b14ed97071a409a061e66679990ecbfb934a1ebe

record OptimizerStateCapabilities
  member reset_supported: Bool
  member no_cross_case_state: Bool
  member cancelled: Bool

fn decide(input: OptimizerStateCapabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.reset_supported else "optimizer_reset_unavailable"
  requires input.no_cross_case_state else "optimizer_state_contamination"
  return ok {'optimizer_state_policy': 'reset_each_case'}
