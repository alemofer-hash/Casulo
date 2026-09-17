language T/1.1
module generated.review

capability manifest

field Input
  trace value: Text

condense Act in Input
  effects [manifest]
  emit "revisão com confirmação"
