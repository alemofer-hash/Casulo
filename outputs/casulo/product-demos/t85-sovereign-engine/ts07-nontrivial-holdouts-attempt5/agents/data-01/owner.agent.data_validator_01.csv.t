language T/2.0
module owner.agent.data_validator_01.csv
budget steps 4096
budget deadline_ms 3000
schema version 1

record PolicyInput
  member confirmed: Bool
  member project_match: Bool
  member evidence_statuses: List<Text,32>
  member preserve_original_bytes: Bool
  member apply_versioned_schema: Bool
  member provide_diagnostic_per_rejection: Bool
  member cancelled: Bool

enum PolicyDecision
  case READY
  case BLOCKED

state accepted: Int = 0

fn verify_preserve_original_bytes(input: PolicyInput) -> Result<Text,Text>
  requires input.preserve_original_bytes else "csv_preserve_bytes_failed"
  return ok "BYTES_PRESERVED"

fn verify_apply_versioned_schema(input: PolicyInput) -> Result<Text,Text>
  requires input.apply_versioned_schema else "schema_version_mismatch"
  return ok "SCHEMA_VERSIONED"

fn verify_provide_diagnostic_per_rejection(input: PolicyInput) -> Result<Text,Text>
  requires input.provide_diagnostic_per_rejection else "diag_missing_for_rejection"
  return ok "DIAGNOSTIC_PROVIDED"

fn branch(input: PolicyInput) -> Result<Text,Text>
  if input.confirmed
    return ok "CONFIRMED"
  else
    return error "human_confirmation_required"

fn decide(input: PolicyInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.confirmed else "human_confirmation_required"
  requires input.project_match else "project_scope_mismatch"
  requires input.preserve_original_bytes else "csv_preserve_bytes_failed"
  requires input.apply_versioned_schema else "schema_version_mismatch"
  requires input.provide_diagnostic_per_rejection else "diag_missing_for_rejection"
  for status in input.evidence_statuses limit 32
    requires status == "PASS" else "evidence_not_pass"
  set state.accepted = add(state.accepted, 1)
  spawn job audit using input.evidence_statuses limit 32
  join job audit
  return ok "READY"
