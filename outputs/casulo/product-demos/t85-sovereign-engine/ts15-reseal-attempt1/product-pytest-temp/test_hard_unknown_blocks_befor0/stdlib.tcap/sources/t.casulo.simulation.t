language T/2.0
module t.casulo.simulation
use t.casulo.universes
budget steps 256
budget deadline_ms 1000
schema version 1
capability simulation

record SimulationInput
  member previous: Text
  member sandboxed: Bool

fn decide(input: SimulationInput) -> Result<Text,Text>
  effects [simulation]
  requires input.previous == "ROUTED" else "universe_chain_broken"
  requires input.sandboxed else "real_effect_denied_in_simulation"
  request effect simulation
  return ok "SIMULATED"
