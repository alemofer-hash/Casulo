language T/2.0
module owner.publish
budget steps 4096
budget deadline_ms 5000
schema version 1
capability manifest

record PublishInput
  member confirmed: Bool
  member hard_statuses: List<Text,64>
  member cancelled: Bool

enum PublishDecision
  case PUBLISH
  case BLOCKED

state attempts: Int = 0

fn decide(input: PublishInput) -> Result<Text,Text>
  effects [manifest]
  cancel if input.cancelled
  requires input.confirmed else "intent_unconfirmed"
  for status in input.hard_statuses limit 64
    requires status == "PASS" else "hard_requirement_not_pass"
  set state.attempts = add(state.attempts, 1)
  spawn job audit using input.hard_statuses limit 64
  join job audit
  request effect manifest
  if input.confirmed
    return ok "ALTERED"
  else
    return error "BLOCKED"

