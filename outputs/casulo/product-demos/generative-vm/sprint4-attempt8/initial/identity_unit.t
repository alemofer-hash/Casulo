language T/1.1
module identity

capability manifest

field Farol_de_Decisoes
  trace value: Text

condense Identidade_Farol in Farol_de_Decisoes
  effects [manifest]
  emit "Farol de Decisões"
