language T/2.0
module owner.agent.datavalidator.byte_preserver
budget steps 4096
budget deadline_ms 3000
schema version 1

record PolicyInput
  member confirmed: Bool
  member project_match: Bool
  member evidence_statuses: List<Text,32>
  member preserve_original_bytes: Bool
  member apply_versioned_schema: Bool
  member provide_rejection_diagnostic: Bool
  member cancelled: Bool

enum PolicyDecision
  case READY
  case BLOCKED

state accepted: Int = 0

fn verify_preserve_original_bytes(input: PolicyInput) -> Result<Text,Text>
  requires input.preserve_original_bytes else "datavalidator_byte_preservation_failed"
  return ok "ORIGINAL_PRESERVED_SATISFIED"

fn verify_apply_versioned_schema(input: PolicyInput) -> Result<Text,Text>
  requires input.apply_versioned_schema else "datavalidator_schema_version_mismatch"
  return ok "VERSIONED_SCHEMA_SATISFIED"

fn verify_provide_rejection_diagnostic(input: PolicyInput) -> Result<Text,Text>
  requires input.provide_rejection_diagnostic else "datavalidator_rejection_explanation_missing"
  return ok "DIAGNOSTIC_PER_REJECTION_SATISFIED"

fn branch(input: PolicyInput) -> Result<Text,Text>
  if input.confirmed
    return ok "CONFIRMED"
  else
    return error "human_confirmation_required"

fn decide(input: PolicyInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.confirmed else "human_confirmation_required"
  requires input.project_match else "project_scope_mismatch"
  requires input.preserve_original_bytes else "datavalidator_byte_preservation_failed"
  requires input.apply_versioned_schema else "datavalidator_schema_version_mismatch"
  requires input.provide_rejection_diagnostic else "datavalidator_rejection_explanation_missing"
  for status in input.evidence_statuses limit 32
    requires status == "PASS" else "evidence_not_pass"
  set state.accepted = add(state.accepted, 1)
  spawn job audit using input.evidence_statuses limit 32
  join job audit
  return ok "READY"
