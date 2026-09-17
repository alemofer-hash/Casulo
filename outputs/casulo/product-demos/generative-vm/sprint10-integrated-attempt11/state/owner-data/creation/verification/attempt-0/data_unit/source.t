language T/1.1
module data

capability manifest

field Storage
  trace value: Text

condense Enable in Storage
  effects [manifest]
  emit "true"
