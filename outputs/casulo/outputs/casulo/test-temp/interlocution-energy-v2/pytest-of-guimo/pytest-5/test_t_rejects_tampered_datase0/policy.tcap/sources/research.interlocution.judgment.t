language T/2.0
module research.interlocution.judgment
budget steps 4096
budget deadline_ms 5000
schema version 1
# training-authority-plan 7516a0da239ef899d45532c839a87c906cb46b793061ac3a6d481bb002c9252a

record JudgeCapabilities
  member independent_verifier_available: Bool
  member publisher_requires_t: Bool
  member cancelled: Bool

fn policy(input: JudgeCapabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.independent_verifier_available else "independent_verifier_unavailable"
  requires input.publisher_requires_t else "publisher_bypass_detected"
  return ok {'absolute_tolerance': '1e-09', 'require_exact_counters': 'true', 'require_no_nan_inf': 'true'}

record JudgmentEvidence
  member equivalence_status: Text
  member counter_status: Text
  member receipt_status: Text
  member semantic_status: Text
  member human_contract_confirmed: Bool
  member cancelled: Bool

fn judge(input: JudgmentEvidence) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.equivalence_status == 'PASS' else "equivalence_not_pass"
  requires input.counter_status == 'PASS' else "counters_not_pass"
  requires input.receipt_status == 'PASS' else "receipts_not_pass"
  requires input.semantic_status == 'PASS' else "semantic_integrity_not_pass"
  requires input.human_contract_confirmed else "human_contract_unconfirmed"
  return ok {'decision': 'PUBLISH'}
