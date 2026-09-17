language T/1.1
module validation

capability manifest

field CreationSpec
  trace value: Text

condense Confirm in CreationSpec
  effects [manifest]
  emit "casulo.creation/1.0"
