language T/2.0
module research.interlocution.stopping
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 18bfc5d0d80fe52c347744ba7ca330653e7ba064ecba2f406efe63f05e8ded4e

record StoppingCapabilities
  member fixed_epoch_supported: Bool
  member counter_supported: Bool
  member cancelled: Bool

fn decide(input: StoppingCapabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.fixed_epoch_supported else "fixed_epoch_stop_unavailable"
  requires input.counter_supported else "epoch_counter_unavailable"
  return ok {'stopping_policy': 'fixed_epochs', 'epochs': '399'}
