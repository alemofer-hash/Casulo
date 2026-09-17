language T/2.0
module owner.critical.intent
budget steps 256
budget deadline_ms 1000
schema version 1

record MaterialIntentInput
  member model_proposed: Bool
  member human_confirmed: Bool
  member material: Bool
  member cancelled: Bool

fn decide(input: MaterialIntentInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.model_proposed else "intent_proposal_missing"
  requires input.human_confirmed else "human_confirmation_required"
  requires input.material else "non_material_intent"
  return error "mutated_policy_denied"
