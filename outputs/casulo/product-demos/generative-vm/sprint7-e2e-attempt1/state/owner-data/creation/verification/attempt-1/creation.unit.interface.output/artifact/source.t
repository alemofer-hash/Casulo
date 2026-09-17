language T/1.1
module interface

capability manifest

field OutputFormat
  trace value: Text

condense Construct in OutputFormat
  effects [manifest]
  emit "StructuredOutputConstruction"
