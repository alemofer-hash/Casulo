field Sample
  trace value: Number
  trace valid: Bool

condense Broken in Sample
  if valid
    emit value
  else
    emit "none"
