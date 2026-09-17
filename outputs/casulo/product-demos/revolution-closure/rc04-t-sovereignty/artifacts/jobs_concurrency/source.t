language T/1.1
module casulo.revolution.jobs

capability manifest

record JobDecision
  trace receipt_present: Bool
  trace cancelled: Bool
  trace generation_matches: Bool

condense PublishJob in JobDecision
  effects [manifest]
  if receipt_present
    if cancelled
      emit "DROP_STALE"
    else
      if generation_matches
        emit "PUBLISH"
      else
        emit "DROP_STALE"
  else
    emit "WAIT"
