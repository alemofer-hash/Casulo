language T/1.1
module capabilities

capability manifest

field Manifest
  trace value: Text

condense ValidateCapabilities in Manifest
  effects [manifest]
  emit "memory.read"
