language T/2.0
module research.interlocution.holdout.holdout_logistic_bce_subset_v1.equivalence_acceptance
budget steps 4096
budget deadline_ms 5000
schema version 1
# holdout-spec 83625e44cb4b25345cb879805749757aee6700e7034d9bbd0264a07308db9e7e

record Capabilities
  member supported: Bool
  member publisher_requires_t: Bool
  member cancelled: Bool

fn policy(input: Capabilities) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.supported else "verifier_unavailable"
  requires input.publisher_requires_t else "publisher_bypass"
  return ok {'absolute_tolerance': '1e-09', 'require_exact_counters': 'true', 'require_no_nan_inf': 'true'}

record Evidence
  member equivalence_status: Text
  member counter_status: Text
  member receipt_status: Text
  member semantic_status: Text
  member human_contract_confirmed: Bool
  member cancelled: Bool

fn judge(input: Evidence) -> Result<Map<Text,Text,32>,Text>
  cancel if input.cancelled
  requires input.equivalence_status == 'PASS' else "equivalence_not_pass"
  requires input.counter_status == 'PASS' else "counters_not_pass"
  requires input.receipt_status == 'PASS' else "receipts_not_pass"
  requires input.semantic_status == 'PASS' else "semantic_not_pass"
  requires input.human_contract_confirmed else "human_contract_unconfirmed"
  return ok {'decision': 'PUBLISH'}
