language T/1.1
module effects

capability manifest

field CreationSpec
  trace value: Text

condense Manifest in CreationSpec
  effects [manifest]
  emit "manifest:memory.read"
