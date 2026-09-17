language T/1.1
module creation

capability manifest

field CreationSpec
  trace value: Text

condense Initialize in CreationSpec
  effects [manifest]
  emit "Initialization of simulated environment for vibration analysis farol Q83 âmbar reversível"
