language T/2.0
module owner.agent.t_interactive_01.memory
budget steps 4096
budget deadline_ms 3000
schema version 1

record PolicyInput
  member confirmed: Bool
  member project_match: Bool
  member evidence_statuses: List<Text,32>
  member is_project_isolated: Bool
  member is_barge_in_allowed: Bool
  member is_export_editable: Bool
  member cancelled: Bool

enum PolicyDecision
  case READY
  case BLOCKED

state accepted: Int = 0

fn verify_is_project_isolated(input: PolicyInput) -> Result<Text,Text>
  requires input.is_project_isolated else "t_interactive_01_memory_01"
  return ok "PROJECT_ISOLATION_SATISFIED"

fn verify_is_barge_in_allowed(input: PolicyInput) -> Result<Text,Text>
  requires input.is_barge_in_allowed else "t_interactive_01_interrupt_01"
  return ok "BARGE_IN_SATISFIED"

fn verify_is_export_editable(input: PolicyInput) -> Result<Text,Text>
  requires input.is_export_editable else "t_interactive_01_export_01"
  return ok "EDITABLE_EXPORT_SATISFIED"

fn branch(input: PolicyInput) -> Result<Text,Text>
  if input.confirmed
    return ok "CONFIRMED"
  else
    return error "human_confirmation_required"

fn decide(input: PolicyInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.confirmed else "human_confirmation_required"
  requires input.project_match else "project_scope_mismatch"
  requires input.is_project_isolated else "t_interactive_01_memory_01"
  requires input.is_barge_in_allowed else "t_interactive_01_interrupt_01"
  requires input.is_export_editable else "t_interactive_01_export_01"
  for status in input.evidence_statuses limit 32
    requires status == "PASS" else "evidence_not_pass"
  set state.accepted = add(state.accepted, 1)
  spawn job audit using input.evidence_statuses limit 32
  join job audit
  return ok "READY"
