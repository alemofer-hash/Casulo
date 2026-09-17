field Sample
  trace value: Number

condense Classify in Sample
  if value >= 0
    emit true
  else
    emit false
