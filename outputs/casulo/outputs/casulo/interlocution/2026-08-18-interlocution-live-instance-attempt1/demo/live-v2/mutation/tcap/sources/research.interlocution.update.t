language T/2.0
module research.interlocution.update
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan e3c8959ba9187e6c5053eb50b14ed97071a409a061e66679990ecbfb934a1ebe

record UpdateCapabilities
  member sgd_supported: Bool
  member cancelled: Bool

fn decide(input: UpdateCapabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.sgd_supported else "sgd_primitive_unavailable"
  return ok {'optimizer': 'sgd', 'learning_rate': '0.009'}
