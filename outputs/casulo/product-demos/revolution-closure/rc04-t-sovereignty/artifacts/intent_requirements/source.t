language T/1.1
module casulo.revolution.requirements

capability manifest

record RequirementDecision
  trace schema_valid: Bool
  trace evidence_present: Bool
  trace safety_pass: Bool

condense EvaluateRequirement in RequirementDecision
  effects [manifest]
  if schema_valid
    if evidence_present
      if safety_pass
        emit "PASS"
      else
        emit "FAIL"
    else
      emit "UNKNOWN"
  else
    emit "FAIL"
