language T/1.1
module trace

capability manifest

field B14C
  trace value: Text

condense B14C_trace in B14C
  effects [manifest]
  emit "B14C: trace value: 'Creation of B14C'"
