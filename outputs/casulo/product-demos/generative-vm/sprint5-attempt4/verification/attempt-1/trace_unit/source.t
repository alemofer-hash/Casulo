language T/1.1
module trace

capability manifest

field TraceValue
  trace value: Text

condense Log in TraceValue
  effects [manifest]
  emit "Cartografo de Duvidas - Trace: Research Conversation"
