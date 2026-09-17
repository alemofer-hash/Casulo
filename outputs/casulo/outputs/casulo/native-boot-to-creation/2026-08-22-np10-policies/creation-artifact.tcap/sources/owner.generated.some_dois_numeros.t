language T/2.0
module owner.generated.some_dois_numeros
budget steps 64
budget deadline_ms 1000
schema version 1

record SomeDoisNumerosInput
  member left: Int
  member right: Int
  member cancelled: Bool

fn execute(input: SomeDoisNumerosInput) -> Result<Int,Text>
  cancel if input.cancelled
  return ok add(input.left, input.right)
