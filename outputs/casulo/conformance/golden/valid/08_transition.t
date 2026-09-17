field Raw
  trace value: Number

field Stable
  trace value: Number

transition Validate
  from Raw
  to Stable
  judge value >= 0
  stabilize value
  emit value
