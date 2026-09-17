language T/1.1
module generated.decision

capability manifest

field Input
  trace value: Text

condense Act in Input
  effects [manifest]
  emit "decisão"
