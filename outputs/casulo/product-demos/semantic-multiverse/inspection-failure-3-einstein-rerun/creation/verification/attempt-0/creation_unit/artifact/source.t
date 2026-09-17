language T/1.1
module creation

capability manifest

field CreationSpec
  trace value: Text

condense Initialize in CreationSpec
  effects [manifest]
  emit "manifest: memory.read, trace: 'Creation started', effects: [manifest], emit: 'Initialization complete.'"
