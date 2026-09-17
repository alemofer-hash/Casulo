language T/1.1
module casulo.revolution.interfaces

capability manifest

record InterfaceDecision
  trace event_valid: Bool
  trace receipt_present: Bool

condense RenderState in InterfaceDecision
  effects [manifest]
  if event_valid
    if receipt_present
      emit "RENDER"
    else
      emit "WAIT"
  else
    emit "RECOVERABLE_ERROR"
