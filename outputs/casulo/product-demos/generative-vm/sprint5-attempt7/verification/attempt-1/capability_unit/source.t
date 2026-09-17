language T/1.1
module capabilities

capability manifest

field MemoryRead
  trace value: Text

condense AccessResearchLogs in MemoryRead
  effects [manifest]
  emit "AccessResearchLogs: Retrieve and analyze historical research logs to inform current hypothesis evaluation."
