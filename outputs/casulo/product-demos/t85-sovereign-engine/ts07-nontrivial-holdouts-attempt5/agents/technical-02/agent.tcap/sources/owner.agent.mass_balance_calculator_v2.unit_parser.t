language T/2.0
module owner.agent.mass_balance_calculator_v2.unit_parser
budget steps 4096
budget deadline_ms 3000
schema version 1

record PolicyInput
  member confirmed: Bool
  member project_match: Bool
  member evidence_statuses: List<Text,32>
  member unit_consistent: Bool
  member mass_conserved: Bool
  member residual_valid: Bool
  member cancelled: Bool

enum PolicyDecision
  case READY
  case BLOCKED

state accepted: Int = 0

fn verify_unit_consistent(input: PolicyInput) -> Result<Text,Text>
  requires input.unit_consistent else "invalid_unit_format"
  return ok "UNIT_FORMAT_VALID"

fn verify_mass_conserved(input: PolicyInput) -> Result<Text,Text>
  requires input.mass_conserved else "mass_mismatch_detected"
  return ok "MASS_CONSERVED"

fn verify_residual_valid(input: PolicyInput) -> Result<Text,Text>
  requires input.residual_valid else "residual_unit_mismatch"
  return ok "RESIDUAL_UNITS_MATCH"

fn branch(input: PolicyInput) -> Result<Text,Text>
  if input.confirmed
    return ok "CONFIRMED"
  else
    return error "human_confirmation_required"

fn decide(input: PolicyInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.confirmed else "human_confirmation_required"
  requires input.project_match else "project_scope_mismatch"
  requires input.unit_consistent else "invalid_unit_format"
  requires input.mass_conserved else "mass_mismatch_detected"
  requires input.residual_valid else "residual_unit_mismatch"
  for status in input.evidence_statuses limit 32
    requires status == "PASS" else "evidence_not_pass"
  set state.accepted = add(state.accepted, 1)
  spawn job audit using input.evidence_statuses limit 32
  join job audit
  return ok "READY"
