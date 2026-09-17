language T/1.1
module casulo.product.presence

capability manifest

field PresenceEvent
  trace message: Text

condense Present in PresenceEvent
  effects [manifest]
  emit message
