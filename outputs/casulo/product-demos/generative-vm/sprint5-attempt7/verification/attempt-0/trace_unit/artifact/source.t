language T/1.1
module trace

capability manifest

field TextualTrace
  trace value: Text

condense LogConversations in TextualTrace
  effects [manifest]
  emit "LogConversations: Record and structure research conversations to track hypothesis development and evidence evaluation."
