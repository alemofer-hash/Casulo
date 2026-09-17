language T/1.1
module casulo.external.proof

capability manifest

field Input
  trace value: Text

condense MaterializedAnswer in Input
  effects [manifest]
  emit "resposta externa Casulo"
