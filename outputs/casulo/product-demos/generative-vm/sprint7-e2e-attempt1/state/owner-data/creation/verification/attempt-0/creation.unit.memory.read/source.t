language T/1.1
module memory.read

capability manifest

field CreationSpec
  trace value: Text

condense Initialize in CreationSpec
  effects [manifest]
  emit "MemoryReadInitialization"
