language T/2.0
module t.casulo.jobs
use t.casulo.memory_policy
budget steps 1024
budget deadline_ms 1000
schema version 1

record JobInput
  member previous: Text
  member cancelled: Bool
  member payload: Text

state dispatched: Int = 0

fn decide(input: JobInput) -> Result<Text,Text>
  requires input.previous == "MEMORY_SELECTED" else "memory_chain_broken"
  cancel if input.cancelled
  set state.dispatched = add(state.dispatched, 1)
  spawn job work using input.payload limit 8
  join job work
  return ok "JOBS_READY"
