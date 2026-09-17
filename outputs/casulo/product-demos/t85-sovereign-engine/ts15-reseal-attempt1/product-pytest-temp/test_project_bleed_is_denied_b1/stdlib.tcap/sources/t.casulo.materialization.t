language T/2.0
module t.casulo.materialization
use t.casulo.simulation
budget steps 256
budget deadline_ms 1000
schema version 1
capability manifest

record MaterializationInput
  member previous: Text
  member approved: Bool

fn decide(input: MaterializationInput) -> Result<Text,Text>
  effects [manifest]
  requires input.previous == "SIMULATED" else "simulation_chain_broken"
  requires input.approved else "publish_approval_required"
  request effect manifest
  return ok "PUBLISHED"
