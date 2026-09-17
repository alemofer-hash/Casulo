language T/2.0
module research.interlocution.update
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 7516a0da239ef899d45532c839a87c906cb46b793061ac3a6d481bb002c9252a

record UpdateCapabilities
  member sgd_supported: Bool
  member cancelled: Bool

fn decide(input: UpdateCapabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.sgd_supported else "sgd_primitive_unavailable"
  return ok {'optimizer': 'sgd', 'learning_rate': '0.018'}
