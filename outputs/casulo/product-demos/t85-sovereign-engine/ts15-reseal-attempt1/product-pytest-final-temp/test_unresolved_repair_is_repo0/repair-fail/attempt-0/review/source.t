language T/1.1
module generated.review

capability manifest

field ReviewInput
  trace value: Text

condense ReviewDecision in ReviewInput
  effects [manifest]
  emit "revisão"
