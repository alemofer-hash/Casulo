language T/1.1
module trace

capability manifest

field CreationSpec
  trace value: Text

condense Log in CreationSpec
  effects [manifest]
  emit "Text:creation:open-ended-holdout"
