field Sample
  trace value: Number
  trace valid: Bool

condense Choose in Sample
  if valid
    emit value
  else
    emit 0
