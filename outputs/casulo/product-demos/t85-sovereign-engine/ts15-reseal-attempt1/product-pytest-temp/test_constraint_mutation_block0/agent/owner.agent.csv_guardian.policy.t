language T/2.0
module owner.agent.csv_guardian.policy
budget steps 4096
budget deadline_ms 3000
schema version 1

record PolicyInput
  member confirmed: Bool
  member project_match: Bool
  member evidence_statuses: List<Text,32>
  member bytes_preserved: Bool
  member schema_versioned: Bool
  member diagnostics_ready: Bool
  member cancelled: Bool

enum PolicyDecision
  case READY
  case BLOCKED

state accepted: Int = 0

fn verify_bytes_preserved(input: PolicyInput) -> Result<Text,Text>
  requires input.bytes_preserved else "original_missing"
  return ok "BYTES_PRESERVED"

fn verify_schema_versioned(input: PolicyInput) -> Result<Text,Text>
  requires input.schema_versioned else "schema_missing"
  return ok "SCHEMA_OK"

fn verify_diagnostics_ready(input: PolicyInput) -> Result<Text,Text>
  requires input.diagnostics_ready else "diagnostics_missing"
  return ok "DIAGNOSTICS_OK"

fn branch(input: PolicyInput) -> Result<Text,Text>
  if input.confirmed
    return ok "CONFIRMED"
  else
    return error "human_confirmation_required"

fn decide(input: PolicyInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.confirmed else "human_confirmation_required"
  requires input.project_match else "project_scope_mismatch"
  requires input.bytes_preserved else "original_missing"
  requires input.schema_versioned else "schema_missing"
  requires input.diagnostics_ready else "diagnostics_missing"
  for status in input.evidence_statuses limit 32
    requires status == "PASS" else "evidence_not_pass"
  set state.accepted = add(state.accepted, 1)
  spawn job audit using input.evidence_statuses limit 32
  join job audit
  return ok "READY"
