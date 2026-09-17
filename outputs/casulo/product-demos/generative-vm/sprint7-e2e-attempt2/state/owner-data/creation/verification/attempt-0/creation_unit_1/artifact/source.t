language T/1.1
module creation

capability manifest

field Buzina
  trace value: Text

condense InitializeReversibility in Buzina
  effects [manifest]
  emit "Initialization of Reversibility Module: Bússola de Reversibilidade is now active."
