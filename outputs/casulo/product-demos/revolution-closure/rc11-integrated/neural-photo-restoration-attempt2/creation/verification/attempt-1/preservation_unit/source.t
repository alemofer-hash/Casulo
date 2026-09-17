language T/1.1
module preservation

capability manifest

field PreservationSpec
  trace value: Text

condense Record in PreservationSpec
  effects [manifest]
  emit "preservation:log"
