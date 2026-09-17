language T/2.0
module owner.guide.context_policy
budget steps 2048
budget deadline_ms 3000
schema version 1

record ContextPolicyInput
  member project_match: Bool
  member budget_valid: Bool
  member mandatory_preserved: Bool
  member ambiguity_present: Bool
  member human_resolution_present: Bool
  member cancelled: Bool

enum ContextDecision
  case SELECT
  case ASK_HUMAN

state selections: Int = 0

fn decide(input: ContextPolicyInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.project_match else "project_scope_mismatch"
  requires input.budget_valid else "context_budget_invalid"
  requires input.mandatory_preserved else "hard_constraint_loss"
  if input.ambiguity_present
    if input.human_resolution_present
      set state.selections = add(state.selections, 1)
      return ok "SELECT"
    else
      return ok "ASK_HUMAN"
  else
    set state.selections = add(state.selections, 1)
    return ok "SELECT"
