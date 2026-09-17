language T/2.0
module owner.materialization.lifecycle
budget steps 2048
budget deadline_ms 3000
schema version 2
capability manifest

record MaterializationInput
  member action: Text
  member previous: Text
  member human_approved: Bool
  member simulation_status: Text
  member effects_safe: Bool
  member candidate_hash: Text
  member candidate_hash_valid: Bool
  member atomic_ready: Bool
  member cancelled: Bool

enum MaterializationDecision
  case PREPARED
  case SEALED
  case PUBLISH

fn decide(input: MaterializationInput) -> Result<Text,Text>
  effects [manifest]
  cancel if input.cancelled
  if input.action == "PREPARE"
    requires input.previous == "FULFILLED" else "hard_fulfillment_required"
    requires input.human_approved else "publish_human_approval_required"
    requires input.simulation_status == "PASS" else "simulation_pass_required"
    requires input.effects_safe else "real_effect_or_secret_denied"
    return ok "PREPARED"
  else
    if input.action == "SEAL"
      requires input.previous == "PREPARED" else "prepare_receipt_required"
      requires len(input.candidate_hash) != 0 else "candidate_hash_missing"
      requires input.candidate_hash_valid else "candidate_hash_invalid"
      return ok "SEALED"
    else
      if input.action == "PUBLISH"
        requires input.previous == "SEALED" else "seal_receipt_required"
        requires len(input.candidate_hash) != 0 else "candidate_hash_missing"
        requires input.candidate_hash_valid else "candidate_hash_invalid"
        requires input.atomic_ready else "atomic_publish_unavailable"
        request effect manifest
        return ok "PUBLISH"
      else
        return error "unknown_materialization_action"
