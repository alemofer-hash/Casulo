language T/1.1
module trace

capability manifest

field TraceValue
  trace value: Text

condense Record in TraceValue
  effects [manifest]
  emit "Text:reversible_decisions"
