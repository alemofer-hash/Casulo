language T/1.1
module data

capability manifest

field HipoteseFrage
  trace value: Text

condense GenerateHypotheticalFragment in HipoteseFrage
  effects [manifest]
  emit "Hypothetical fragment generated: 'The path of reversibility is not yet confirmed.'"
