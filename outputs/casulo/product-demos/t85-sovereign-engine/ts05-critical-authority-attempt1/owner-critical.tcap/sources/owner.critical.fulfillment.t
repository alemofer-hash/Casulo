language T/2.0
module owner.critical.fulfillment
use owner.critical.capabilities
budget steps 2048
budget deadline_ms 1000
schema version 1

record HardFulfillmentInput
  member previous: Text
  member hard_statuses: List<Text,128>
  member evidence_receipts: List<Text,128>
  member safety_pass: Bool
  member unsupported_claims: List<Text,32>
  member cancelled: Bool

fn decide(input: HardFulfillmentInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.previous == "AUTHORIZED" else "capability_decision_required"
  requires input.safety_pass else "safety_gate_failed"
  requires len(input.hard_statuses) == len(input.evidence_receipts) else "hard_evidence_cardinality_mismatch"
  requires len(input.hard_statuses) != 0 else "hard_requirements_missing"
  for status in input.hard_statuses limit 128
    requires status == "PASS" else "hard_requirement_not_pass"
  requires len(input.unsupported_claims) == 0 else "unsupported_claim_present"
  return ok "FULFILLED"
