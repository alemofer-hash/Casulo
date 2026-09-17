language T/1.1
module trace

capability manifest

field TraceSpec
  trace value: Text

condense Log in TraceSpec
  effects [manifest]
  emit "trace:log"
