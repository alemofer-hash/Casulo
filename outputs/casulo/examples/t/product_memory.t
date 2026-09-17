language T/1.1
module casulo.product.memory

capability manifest

enum RecallError
  case NotFound
  case Ambiguous

record MemoryQuery
  trace text: Text

record RecallReply
  trace outcome: Result[Text, RecallError]

condense Recall in MemoryQuery
  effects [manifest]
  if text == ""
    emit "missing"
  else
    emit text
