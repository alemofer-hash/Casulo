language T/1.1
module creation

capability manifest

field CreationSpec
  trace value: Text

condense InitializeCreation in CreationSpec
  effects [manifest]
  emit "capabilities: memory.read,trilho D39E reversível"
