language T/2.0
module t.casulo.requirements
use t.casulo.intent
budget steps 1024
budget deadline_ms 1000
schema version 1

record RequirementsInput
  member previous: Text
  member hard_statuses: List<Text,64>

fn decide(input: RequirementsInput) -> Result<Text,Text>
  requires input.previous == "MATERIAL" else "intent_chain_broken"
  for status in input.hard_statuses limit 64
    requires status == "PASS" else "hard_requirement_not_pass"
  return ok "VERIFIED"
