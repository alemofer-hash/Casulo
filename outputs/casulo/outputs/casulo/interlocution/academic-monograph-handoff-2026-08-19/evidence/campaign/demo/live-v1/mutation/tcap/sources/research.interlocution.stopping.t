language T/2.0
module research.interlocution.stopping
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan e3c8959ba9187e6c5053eb50b14ed97071a409a061e66679990ecbfb934a1ebe

record StoppingCapabilities
  member fixed_epoch_supported: Bool
  member counter_supported: Bool
  member cancelled: Bool

fn decide(input: StoppingCapabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.fixed_epoch_supported else "fixed_epoch_stop_unavailable"
  requires input.counter_supported else "epoch_counter_unavailable"
  return ok {'stopping_policy': 'fixed_epochs', 'epochs': '400'}
