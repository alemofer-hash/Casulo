language T/1.1
module generated.output

capability manifest

field Input
  trace value: Text

condense Act in Input
  effects [manifest]
  emit "saída"
