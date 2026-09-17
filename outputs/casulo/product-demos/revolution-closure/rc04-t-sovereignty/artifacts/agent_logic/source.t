language T/1.1
module casulo.revolution.agent

capability manifest

record AgentDecision
  trace intent_confirmed: Bool
  trace constraints_satisfied: Bool
  trace cancelled: Bool

condense AdvanceAgent in AgentDecision
  effects [manifest]
  if intent_confirmed
    if constraints_satisfied
      if cancelled
        emit "CANCELLED"
      else
        emit "READY"
    else
      emit "BLOCKED"
  else
    emit "WAIT_CONFIRMATION"
