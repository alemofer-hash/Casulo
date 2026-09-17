language T/2.0
module owner.agent.ts14_mycelium_reconciler.growth
budget steps 4096
budget deadline_ms 3000
schema version 1

record PolicyInput
  member confirmed: Bool
  member project_match: Bool
  member evidence_statuses: List<Text,32>
  member preserve_lab_notebook_bytes: Bool
  member normalize_growth_units_with_prov: Bool
  member emit_protocol_with_uncert: Bool
  member cancelled: Bool

enum PolicyDecision
  case READY
  case BLOCKED

state accepted: Int = 0

fn verify_preserve_lab_notebook_bytes(input: PolicyInput) -> Result<Text,Text>
  requires input.preserve_lab_notebook_bytes else "invalid_byte_preservation"
  return ok "PRESERVE_LAB_NOTEBOOK_BYTES_SATISFIED"

fn verify_normalize_growth_units_with_prov(input: PolicyInput) -> Result<Text,Text>
  requires input.normalize_growth_units_with_prov else "incompatible_unit_normalization"
  return ok "NORMALIZE_GROWTH_UNITS_WITH_PROVENANCE_SATISFIED"

fn verify_emit_protocol_with_uncert(input: PolicyInput) -> Result<Text,Text>
  requires input.emit_protocol_with_uncert else "protocol_emission_failure"
  return ok "EMIT_REPLICATION_PROTOCOL_W_7846C9D4_SATISFIED"

fn branch(input: PolicyInput) -> Result<Text,Text>
  if input.confirmed
    return ok "CONFIRMED"
  else
    return error "human_confirmation_required"

fn decide(input: PolicyInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.confirmed else "human_confirmation_required"
  requires input.project_match else "project_scope_mismatch"
  requires input.preserve_lab_notebook_bytes else "invalid_byte_preservation"
  requires input.normalize_growth_units_with_prov else "incompatible_unit_normalization"
  requires input.emit_protocol_with_uncert else "protocol_emission_failure"
  for status in input.evidence_statuses limit 32
    requires status == "PASS" else "evidence_not_pass"
  set state.accepted = add(state.accepted, 1)
  spawn job audit using input.evidence_statuses limit 32
  join job audit
  return ok "READY"
