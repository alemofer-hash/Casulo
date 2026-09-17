language T/1.1
module casulo.revolution.simulation

capability manifest

record SimulationDecision
  trace deterministic: Bool
  trace real_effects_absent: Bool
  trace requirements_covered: Bool

condense AcceptSimulation in SimulationDecision
  effects [manifest]
  if deterministic
    if real_effects_absent
      if requirements_covered
        emit "PASS"
      else
        emit "FAIL"
    else
      emit "FAIL"
  else
    emit "FAIL"
