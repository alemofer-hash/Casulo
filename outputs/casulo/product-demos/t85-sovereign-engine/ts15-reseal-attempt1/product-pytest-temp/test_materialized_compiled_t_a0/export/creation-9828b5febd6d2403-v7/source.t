language T/1.1
module generated.external

capability manifest

field Input
  trace value: Text

condense Answer in Input
  effects [manifest]
  emit "resposta materializada"
