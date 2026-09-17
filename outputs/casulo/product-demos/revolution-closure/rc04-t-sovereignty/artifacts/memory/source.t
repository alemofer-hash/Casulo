language T/1.1
module casulo.revolution.memory

capability manifest

record MemoryDecision
  trace schema_valid: Bool
  trace provenance_present: Bool
  trace project_scope_matches: Bool

condense AcceptMemory in MemoryDecision
  effects [manifest]
  if schema_valid
    if provenance_present
      if project_scope_matches
        emit "ACCEPT"
      else
        emit "QUARANTINE"
    else
      emit "QUARANTINE"
  else
    emit "QUARANTINE"
