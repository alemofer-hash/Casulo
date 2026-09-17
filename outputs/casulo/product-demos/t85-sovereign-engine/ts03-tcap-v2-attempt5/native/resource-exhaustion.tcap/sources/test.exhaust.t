language T/2.0
module test.exhaust
budget steps 1
budget deadline_ms 5000
schema version 1

record Input
  member cancelled: Bool

fn decide(input: Input) -> Result<Text,Text>
  cancel if input.cancelled
  return ok "PASS"
