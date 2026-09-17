language T/1.1
module decision

capability manifest

field DecisaoArquitetura
  trace value: Text

condense ReceiveArchitecturalDecision in DecisaoArquitetura
  effects [manifest]
  emit "Architectural decision received: 'The path of reversibility is now confirmed.'"
