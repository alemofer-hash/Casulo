language T/1.1
module identity

capability manifest

field Name
  trace value: Text

condense Assign in Name
  effects [manifest]
  emit "F58G"
