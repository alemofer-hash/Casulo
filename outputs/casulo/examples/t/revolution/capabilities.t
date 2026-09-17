language T/1.1
module casulo.revolution.capabilities

capability manifest

record CapabilityDecision
  trace schema_valid: Bool
  trace policy_pass: Bool
  trace grant_present: Bool
  trace human_approval: Bool

condense DecidePermit in CapabilityDecision
  effects [manifest]
  if schema_valid
    if policy_pass
      if grant_present
        if human_approval
          emit "PERMIT"
        else
          emit "DENY"
      else
        emit "DENY"
    else
      emit "DENY"
  else
    emit "DENY"
