language T/1.1
module effects

capability manifest

field B14C
  trace value: Text

condense B14C_effects in B14C
  effects [manifest]
  emit "B14C: effects [manifest] = 'memory.read()'"
