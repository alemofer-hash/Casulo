language T/1.1
module identity

capability manifest

field Name
  trace value: Text

condense SetIdentity in Name
  effects [manifest]
  emit "Cartografo de Duvidas"
