language T/2.0
module t.casulo.capabilities
use t.casulo.requirements
budget steps 1024
budget deadline_ms 1000
schema version 1

record CapabilityInput
  member previous: Text
  member requested: List<Text,16>
  member granted: List<Text,16>

fn decide(input: CapabilityInput) -> Result<Text,Text>
  requires input.previous == "VERIFIED" else "requirements_chain_broken"
  for capability in input.requested limit 16
    requires contains(input.granted, capability) else "capability_not_granted"
  return ok "AUTHORIZED"
