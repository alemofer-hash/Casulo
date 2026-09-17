language T/2.0
module owner.agent.t_mass_balance.u_check
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
  requires input.unit_consistent else "u_invalid_unit"
  return ok "UNIT_CONSISTENCY_SATISFIED"

fn verify_mass_conserved(input: PolicyInput) -> Result<Text,Text>
  requires input.mass_conserved else "m_discrepancy"
  return ok "MASS_CONSERVATION_SATISFIED"

fn verify_residual_valid(input: PolicyInput) -> Result<Text,Text>
  requires input.residual_valid else "o_nonzero_residual"
  return ok "RESIDUAL_OUTPUT_SATISFIED"

fn branch(input: PolicyInput) -> Result<Text,Text>
  if input.confirmed
    return ok "CONFIRMED"
  else
    return error "human_confirmation_required"

fn decide(input: PolicyInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.confirmed else "human_confirmation_required"
  requires input.project_match else "project_scope_mismatch"
  requires input.unit_consistent else "u_invalid_unit"
  requires input.mass_conserved else "m_discrepancy"
  requires input.residual_valid else "o_nonzero_residual"
  for status in input.evidence_statuses limit 32
    requires status == "PASS" else "evidence_not_pass"
  set state.accepted = add(state.accepted, 1)
  spawn job audit using input.evidence_statuses limit 32
  join job audit
  return ok "READY"
