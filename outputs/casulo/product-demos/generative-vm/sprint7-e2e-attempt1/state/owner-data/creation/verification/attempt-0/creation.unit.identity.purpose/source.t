language T/1.1
module identity

capability manifest

field Purpose
  trace value: Text

condense Define in Purpose
  effects [manifest]
  emit "PurposeDefinition"
