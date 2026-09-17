language T/2.0
module research.interlocution.holdout.holdout_linear_mae_v1.loss_function
budget steps 4096
budget deadline_ms 5000
schema version 1
# holdout-spec 6fed658672c2f5d4bb709fef63c52a93491164f47fb04cbfb070c488bfd31260

record Capabilities
  member supported: Bool
  member cancelled: Bool

fn decide(input: Capabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.supported else "loss_unsupported"
  return ok {'loss': 'mae'}
