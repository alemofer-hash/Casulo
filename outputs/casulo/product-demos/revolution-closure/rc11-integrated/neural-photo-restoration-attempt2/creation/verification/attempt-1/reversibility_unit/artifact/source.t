language T/1.1
module reversibility

capability manifest

field ReversibilitySpec
  trace value: Text

condense Validate in ReversibilitySpec
  effects [manifest]
  emit "reversibility:validation"
