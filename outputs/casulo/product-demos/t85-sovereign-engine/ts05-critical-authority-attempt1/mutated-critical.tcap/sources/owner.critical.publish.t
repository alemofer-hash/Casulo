language T/2.0
module owner.critical.publish
use owner.critical.fulfillment
budget steps 512
budget deadline_ms 1000
schema version 1
capability manifest

record PublishCommitInput
  member previous: Text
  member human_approved: Bool
  member simulation_status: Text
  member cancelled: Bool

fn decide(input: PublishCommitInput) -> Result<Text,Text>
  effects [manifest]
  cancel if input.cancelled
  requires input.previous == "FULFILLED" else "hard_fulfillment_required"
  requires input.human_approved else "publish_human_approval_required"
  requires input.simulation_status == "PASS" else "simulation_pass_required"
  request effect manifest
  return ok "COMMIT"
