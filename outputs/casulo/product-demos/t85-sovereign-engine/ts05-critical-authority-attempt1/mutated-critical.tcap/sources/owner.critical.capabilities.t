language T/2.0
module owner.critical.capabilities
use owner.critical.intent
budget steps 1024
budget deadline_ms 1000
schema version 1

record CapabilityDecisionInput
  member previous: Text
  member requested: List<Text,32>
  member granted: List<Text,32>
  member consent_valid: Bool
  member cancelled: Bool

fn decide(input: CapabilityDecisionInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.previous == "MATERIAL" else "material_intent_required"
  requires input.consent_valid else "valid_consent_required"
  for capability in input.requested limit 32
    requires contains(input.granted, capability) else "capability_not_granted"
  return ok "AUTHORIZED"
