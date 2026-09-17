language T/1.1
module validation

capability manifest

field Validacao_Externa
  trace value: Text

condense Validar_alteracoes in Validacao_Externa
  effects [manifest]
  emit "Validação externa necessária para qualquer alteração ou envio de documentos"
