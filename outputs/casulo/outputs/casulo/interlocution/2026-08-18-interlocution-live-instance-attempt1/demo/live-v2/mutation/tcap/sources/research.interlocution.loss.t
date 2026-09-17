language T/2.0
module research.interlocution.loss
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan e3c8959ba9187e6c5053eb50b14ed97071a409a061e66679990ecbfb934a1ebe

record LossCapabilities
  member mse_supported: Bool
  member cancelled: Bool

fn decide(input: LossCapabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.mse_supported else "mse_primitive_unavailable"
  return ok {'loss': 'mse'}
