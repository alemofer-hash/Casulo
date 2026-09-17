language T/1.1
module memory

capability manifest

field Read
  trace value: Text

condense ReadValue in Read
  effects [manifest]
  emit "manifest: memory.read; trace: 'Memory read'; emit: 'Memory value retrieved.'; comportamento científico"
