field Sample
  trace value: Number

condense Broken in Sample
  if value
    emit value
  else
    emit 0
