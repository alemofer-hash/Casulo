language T/2.0
module t.core.result
budget steps 256
budget deadline_ms 1000
schema version 1

record ResultInput
  member status: Text

enum NormalizedResult
  case PASS
  case BLOCKED

fn decide(input: ResultInput) -> Result<Text,Text>
  requires input.status == "PASS" else "result_not_pass"
  return ok "PASS"
