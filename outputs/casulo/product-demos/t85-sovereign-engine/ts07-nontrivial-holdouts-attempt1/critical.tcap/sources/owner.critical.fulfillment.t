language T/2.0
module owner.critical.fulfillment
use owner.critical.capabilities
budget steps 2048
budget deadline_ms 1000
schema version 1

record HardFulfillmentInput
  member previous: Text
  member graph_schema: Text
  member graph_version: Int
  member project_id: Text
  member candidate_project_id: Text
  member hard_requirement_ids: List<Text,128>
  member expected_evidence_tokens: List<Text,256>
  member observed_evidence_tokens: List<Text,256>
  member evidence_plan_hash: Text
  member safety_pass: Bool
  member unsupported_claims: List<Text,32>
  member cancelled: Bool

fn decide(input: HardFulfillmentInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.previous == "AUTHORIZED" else "capability_decision_required"
  requires input.graph_schema == "casulo.requirement-graph/2.0" else "requirement_graph_schema_invalid"
  requires input.graph_version == 1 else "requirement_graph_version_unsupported"
  requires input.project_id == input.candidate_project_id else "project_scope_mismatch"
  requires len(input.hard_requirement_ids) != 0 else "hard_requirements_missing"
  requires len(input.expected_evidence_tokens) != 0 else "hard_evidence_plan_missing"
  requires len(input.expected_evidence_tokens) == len(input.observed_evidence_tokens) else "hard_evidence_cardinality_mismatch"
  requires len(input.evidence_plan_hash) == 64 else "evidence_plan_hash_invalid"
  requires input.safety_pass else "safety_gate_failed"
  for token in input.expected_evidence_tokens limit 256
    requires contains(input.observed_evidence_tokens, token) else "hard_requirement_not_pass"
  requires len(input.unsupported_claims) == 0 else "unsupported_claim_present"
  return ok "FULFILLED"
