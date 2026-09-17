field Sample
  trace value: Number

condense Normalize in Sample
  judge value >= 0
  restrict value < 1000
  let normalized = value / 1000
  project normalized
  bind normalized with value
  stabilize normalized
  emit normalized
