language T/2.0
module t.casulo.intent
use t.core.canonical
budget steps 256
budget deadline_ms 1000
schema version 1

record IntentInput
  member previous: Text
  member confirmed: Bool
  member material: Bool

enum IntentDecision
  case MATERIAL
  case INFORMAL

fn decide(input: IntentInput) -> Result<Text,Text>
  requires input.previous == "CANONICAL" else "canonical_chain_broken"
  requires input.confirmed else "human_confirmation_required"
  requires input.material else "non_material_turn"
  return ok "MATERIAL"
