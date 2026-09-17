language T/2.0
module owner.multiverse.lifecycle_policy
budget steps 2048
budget deadline_ms 3000
schema version 1

record LifecycleInput
  member action: Text
  member trusted_route: Bool
  member bundle_valid: Bool
  member capability_safe: Bool
  member can_hibernate: Bool
  member sufficient_state_valid: Bool
  member cancelled: Bool

enum LifecycleDecision
  case ACTIVATE
  case HIBERNATE
  case DENY

fn decide(input: LifecycleInput) -> Result<Text,Text>
  cancel if input.cancelled
  if input.action == "ACTIVATE"
    requires input.trusted_route else "route_untrusted"
    requires input.bundle_valid else "bundle_invalid"
    requires input.capability_safe else "capability_amplification"
    return ok "ACTIVATE"
  else
    if input.action == "HIBERNATE"
      requires input.can_hibernate else "lease_or_residency_active"
      requires input.sufficient_state_valid else "sufficient_state_invalid"
      return ok "HIBERNATE"
    else
      return error "unknown_lifecycle_action"
