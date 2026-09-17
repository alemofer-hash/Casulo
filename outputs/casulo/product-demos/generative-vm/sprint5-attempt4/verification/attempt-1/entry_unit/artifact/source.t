language T/1.1
module entry

capability manifest

field EntryPoint
  trace value: Text

condense Start in EntryPoint
  effects [manifest]
  emit "contradicao produtiva"
