language T/1.1
module creation

capability manifest

field Cartografo_de_Duvidas
  trace value: Text

condense RegisterHypotheses in Cartografo_de_Duvidas
  effects [manifest]
  emit "RegisterHypotheses: Create a structured repository for tracking competing hypotheses and their evidence."
