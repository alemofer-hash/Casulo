language T/1.1
module autonomy

capability manifest

field Autonomy
  trace value: Text

condense Process in Autonomy
  effects [manifest]
  emit "manifest: memory.read, trace: 'Processing input', effects: [manifest], emit: 'Autonomy active.'"
