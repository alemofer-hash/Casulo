language T/1.1
module tracing

capability manifest

field TraceValue
  trace value: Text

condense RecordTraceOrigin in TraceValue
  effects [manifest]
  emit "Text"
