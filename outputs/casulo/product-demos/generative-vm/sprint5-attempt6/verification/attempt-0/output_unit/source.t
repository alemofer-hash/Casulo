language T/1.1
module output

capability manifest

field Format
  trace value: Text

condense SetOutputFormat in Format
  effects [manifest]
  emit "structured_text"
