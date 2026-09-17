language T/1.1
module verification

capability manifest

field VerificacaoPequena
  trace value: Text

condense ExecuteSmallVerification in VerificacaoPequena
  effects [manifest]
  emit "Small verification executed: 'The path of reversibility is now under scrutiny.'"
