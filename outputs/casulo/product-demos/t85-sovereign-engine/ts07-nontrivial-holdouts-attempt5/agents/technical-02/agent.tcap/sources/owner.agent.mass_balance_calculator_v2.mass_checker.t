language T/2.0
module owner.agent.mass_balance_calculator_v2.mass_checker
use owner.agent.mass_balance_calculator_v2.unit_parser
budget steps 4096
budget deadline_ms 3000
schema version 1

record WorkflowInput
  member previous: Text
  member evidence_result: Text
  member evidence_statuses: List<Text,32>
  member cancelled: Bool

enum WorkflowDecision
  case PLANNED
  case EVIDENCE_OK
  case WORKFLOW_READY

state transitions: Int = 0

fn plan(input: WorkflowInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.previous == "READY" else "policy_not_ready"
  spawn job prepare using input.evidence_statuses limit 32
  join job prepare
  return ok "PLANNED"

fn check(input: WorkflowInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires len(input.evidence_statuses) != 0 else "evidence_missing"
  for status in input.evidence_statuses limit 32
    requires status == "PASS" else "evidence_not_pass"
  return ok "EVIDENCE_OK"

fn combine(input: WorkflowInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.previous == "PLANNED" else "plan_missing"
  requires input.evidence_result == "EVIDENCE_OK" else "evidence_check_missing"
  set state.transitions = add(state.transitions, 1)
  return ok "WORKFLOW_READY"
