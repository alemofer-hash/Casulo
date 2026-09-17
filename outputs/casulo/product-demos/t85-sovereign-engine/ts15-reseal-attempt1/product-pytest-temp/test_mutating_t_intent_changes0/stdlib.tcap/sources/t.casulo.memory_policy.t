language T/2.0
module t.casulo.memory_policy
use t.casulo.capabilities
budget steps 256
budget deadline_ms 1000
schema version 1

record MemoryInput
  member previous: Text
  member project_id: Text
  member expected_project_id: Text
  member consent: Bool

fn decide(input: MemoryInput) -> Result<Text,Text>
  requires input.previous == "AUTHORIZED" else "capability_chain_broken"
  requires input.project_id == input.expected_project_id else "project_bleed_denied"
  requires input.consent else "memory_consent_required"
  return ok "MEMORY_SELECTED"
