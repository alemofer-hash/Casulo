language T/1.1
module creation

capability manifest

field B14C
  trace value: Text

condense B14C_init in B14C
  effects [manifest]
  emit "B14C: memory.read()"
