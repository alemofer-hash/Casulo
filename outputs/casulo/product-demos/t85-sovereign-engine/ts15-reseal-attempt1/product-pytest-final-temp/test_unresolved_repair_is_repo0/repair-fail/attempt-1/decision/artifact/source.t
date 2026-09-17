language T/1.1
module generated.decision

capability manifest

field DecisionInput
  trace value: Text

condense RememberDecision in DecisionInput
  effects [manifest]
  emit "decisão"
