language T/1.1
module purpose

capability manifest

field Role
  trace value: Text

condense SetPurpose in Role
  effects [manifest]
  emit "research_helper"
