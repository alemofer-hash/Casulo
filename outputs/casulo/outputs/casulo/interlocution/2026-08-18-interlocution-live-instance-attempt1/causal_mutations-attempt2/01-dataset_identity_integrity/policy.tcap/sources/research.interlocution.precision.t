language T/2.0
module research.interlocution.precision
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 18bfc5d0d80fe52c347744ba7ca330653e7ba064ecba2f406efe63f05e8ded4e

record PrecisionCapabilities
  member float64_supported: Bool
  member cancelled: Bool

fn decide(input: PrecisionCapabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.float64_supported else "float64_primitive_unavailable"
  return ok {'dtype': 'float64'}
