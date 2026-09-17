language T/2.0
module owner.agent.mass_balance_calculator_v2.unit_parser
budget steps 4096
budget deadline_ms 3000
schema version 1

record PolicyInput
  member confirmed: Bool
  member project_match: Bool
  member evidence_statuses: List<Text,32>
  member unit_validated: Bool
  member mass_balance_verified: Bool
  member residual_accepted: Bool
  member cancelled: Bool

enum PolicyDecision
  case READY
  case BLOCKED

state accepted: Int = 0

fn verify_unit_validated(input: PolicyInput) -> Result<Text,Text>
  requires input.unit_validated else "invalid_unit"
  return ok "TRUE"

fn verify_mass_balance_verified(input: PolicyInput) -> Result<Text,Text>
  requires input.mass_balance_verified else "mass_discrepancy"
  return ok "TRUE"

fn verify_residual_accepted(input: PolicyInput) -> Result<Text,Text>
  requires input.residual_accepted else "residual_exceeds"
  return ok "FALSE"

fn branch(input: PolicyInput) -> Result<Text,Text>
  if input.confirmed
    return ok "CONFIRMED"
  else
    return error "human_confirmation_required"

fn decide(input: PolicyInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.confirmed else "human_confirmation_required"
  requires input.project_match else "project_scope_mismatch"
  requires input.unit_validated else "invalid_unit"
  requires input.mass_balance_verified else "mass_discrepancy"
  requires input.residual_accepted else "residual_exceeds"
  for status in input.evidence_statuses limit 32
    requires status == "PASS" else "evidence_not_pass"
  set state.accepted = add(state.accepted, 1)
  spawn job audit using input.evidence_statuses limit 32
  join job audit
  return ok "READY"
