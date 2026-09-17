language T/2.0
module owner.math.boundary_policy
budget steps 2048
budget deadline_ms 3000
schema version 1

record MathBoundaryInput
  member equivalence_pass: Bool
  member candidate_measured: Bool
  member candidate_wins: Bool
  member traffic_reduced: Bool
  member fallback_available: Bool
  member implementation_declared: Bool
  member cancelled: Bool

state adopted_kernels: Int = 0

fn decide(input: MathBoundaryInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.implementation_declared else "implementation_boundary_undeclared"
  requires input.fallback_available else "safe_fallback_absent"
  requires input.equivalence_pass else "semantic_equivalence_failed"
  requires input.candidate_measured else "candidate_not_measured"
  requires input.traffic_reduced else "logical_traffic_not_reduced"
  requires input.candidate_wins else "candidate_did_not_win_frozen_threshold"
  set state.adopted_kernels = add(state.adopted_kernels, 1)
  return ok "ADOPT_SPECIALIZED"
