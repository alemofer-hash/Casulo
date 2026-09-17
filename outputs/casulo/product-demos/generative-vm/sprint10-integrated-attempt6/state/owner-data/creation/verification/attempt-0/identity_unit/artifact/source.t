language T/1.1
module identity

capability manifest

field AgentIdentity
  trace value: Text

condense Validate in AgentIdentity
  effects [manifest]
  emit "Text:agent:A92D"
