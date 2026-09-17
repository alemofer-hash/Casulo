language T/1.1
module creation

capability manifest

field CreationSpec
  trace value: Text

condense Initialize in CreationSpec
  effects [manifest]
  emit "preserva o original e produz plano reversível com proveniência, sem efeito destrutivo real; creation:open-ended-holdout"
