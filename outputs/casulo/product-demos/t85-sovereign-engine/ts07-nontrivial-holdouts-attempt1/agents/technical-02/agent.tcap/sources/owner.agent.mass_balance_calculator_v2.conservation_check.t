language T/2.0
module owner.agent.mass_balance_calculator_v2.conservation_check
use owner.agent.mass_balance_calculator_v2.mass_flow
budget steps 2048
budget deadline_ms 3000
schema version 1
capability simulation

record PublishInput
  member previous: Text
  member simulated: Bool
  member approved: Bool
  member cancelled: Bool

enum PublishDecision
  case SIMULATED
  case COMMITTED
  case AUDITED

fn simulate(input: PublishInput) -> Result<Text,Text>
  effects [simulation]
  cancel if input.cancelled
  requires input.previous == "WORKFLOW_READY" else "workflow_not_ready"
  requires input.simulated else "simulation_failed"
  request effect simulation
  return ok "SIMULATED"

fn commit(input: PublishInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.previous == "SIMULATED" else "simulation_receipt_missing"
  requires input.approved else "human_approval_required"
  return ok "COMMITTED"

fn inspect(input: PublishInput) -> Result<Text,Text>
  requires input.previous == "COMMITTED" else "commit_receipt_missing"
  return ok "AUDITED"
