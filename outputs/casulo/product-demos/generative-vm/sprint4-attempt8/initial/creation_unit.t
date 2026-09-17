language T/1.1
module creation

capability manifest

field Farol_de_Decisoes
  trace value: Text

condense Analisar_notas_reuniao in Farol_de_Decisoes
  effects [manifest]
  emit "Analisar notas de reunião, classificar decisões confirmadas vs hipóteses, rastrear contradições em conversas consecutivas"
