language T/2.0
module t.casulo.universes
use t.casulo.jobs
budget steps 256
budget deadline_ms 1000
schema version 1

record UniverseInput
  member previous: Text
  member hot_count: Int
  member max_hot: Int
  member route_allowed: Bool

fn decide(input: UniverseInput) -> Result<Text,Text>
  requires input.previous == "JOBS_READY" else "jobs_chain_broken"
  requires input.hot_count <= input.max_hot else "hot_working_set_exceeded"
  requires input.route_allowed else "semantic_route_denied"
  return ok "ROUTED"
