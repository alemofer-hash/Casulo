field Sample
  trace value: Number
  trace valid: Bool

condense Broken in Sample
  if valid
    let local = value
  emit local
