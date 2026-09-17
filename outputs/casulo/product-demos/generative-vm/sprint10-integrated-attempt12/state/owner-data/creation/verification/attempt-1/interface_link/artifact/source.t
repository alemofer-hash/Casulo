language T/1.1
module interface

capability manifest

field G61H
  trace value: Text

condense G61H_link in G61H
  effects [manifest]
  emit "link:G61H:memory.read:creation:open-ended-holdout"
