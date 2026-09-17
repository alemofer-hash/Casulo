language T/1.1
module data

capability manifest

field G61H
  trace value: Text

condense G61H_reject in G61H
  effects [manifest]
  emit "reject:G61H:memory.read:creation:open-ended-holdout"
