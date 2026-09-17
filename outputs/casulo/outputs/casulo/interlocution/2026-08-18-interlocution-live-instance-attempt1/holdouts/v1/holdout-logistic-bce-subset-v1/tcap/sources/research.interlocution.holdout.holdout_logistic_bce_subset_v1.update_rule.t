language T/2.0
module research.interlocution.holdout.holdout_logistic_bce_subset_v1.update_rule
budget steps 4096
budget deadline_ms 5000
schema version 1
# holdout-spec 83625e44cb4b25345cb879805749757aee6700e7034d9bbd0264a07308db9e7e

record Capabilities
  member supported: Bool
  member cancelled: Bool

fn decide(input: Capabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.supported else "update_unsupported"
  return ok {'optimizer': 'sgd', 'learning_rate': '0.08'}
