language T/1.1
module creation

capability manifest

field G61H
  trace value: Text

condense G61H_init in G61H
  effects [manifest]
  emit "init:G61H:memory.read:creation:open-ended-holdout"
