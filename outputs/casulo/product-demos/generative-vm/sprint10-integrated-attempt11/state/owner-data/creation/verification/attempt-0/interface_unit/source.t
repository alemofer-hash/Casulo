language T/1.1
module interface

capability manifest

field Input
  trace value: Text

condense Register in Input
  effects [manifest]
  emit "registros técnicos incompatíveis, alternativas recusadas"
