language T/1.1
module casulo

capability manifest

field TraceValue
  trace value: Text

condense Log in TraceValue
  effects [manifest]
  emit "CasuloTraceLogging"
