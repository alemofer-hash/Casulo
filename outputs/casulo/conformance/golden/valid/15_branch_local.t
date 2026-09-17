field Sample
  trace value: Number
  trace valid: Bool

condense Choose in Sample
  if valid
    let selected = value
    emit selected
  else
    emit 0
