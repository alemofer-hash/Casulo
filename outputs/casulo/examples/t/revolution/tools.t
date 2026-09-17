language T/1.1
module casulo.revolution.tools

capability manifest

record ToolDecision
  trace schema_valid: Bool
  trace capability_present: Bool
  trace simulation: Bool

condense AuthorizeTool in ToolDecision
  effects [manifest]
  if schema_valid
    if capability_present
      if simulation
        emit "SIMULATE"
      else
        emit "EXECUTE"
    else
      emit "DENY"
  else
    emit "DENY"
