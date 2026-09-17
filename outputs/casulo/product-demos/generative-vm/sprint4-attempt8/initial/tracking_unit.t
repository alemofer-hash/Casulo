language T/1.1
module tracking

capability manifest

field Rastreio_Contradicoes
  trace value: Text

condense Rastrear_contra_dizos in Rastreio_Contradicoes
  effects [manifest]
  emit "Rastreio de contradições entre conversas consecutivas"
