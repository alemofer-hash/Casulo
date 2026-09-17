language T/1.1
module precision

capability manifest

field Level
  trace value: Text

condense SetPrecision in Level
  effects [manifest]
  emit "manifest: precision.level2; trace: 'Precision'; emit: 'Precision level 2 activated.'"
