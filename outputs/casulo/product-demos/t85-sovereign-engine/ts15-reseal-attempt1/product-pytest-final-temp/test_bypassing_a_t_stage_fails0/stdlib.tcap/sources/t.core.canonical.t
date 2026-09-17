language T/2.0
module t.core.canonical
use t.core.collections
budget steps 256
budget deadline_ms 1000
schema version 1

record CanonicalInput
  member previous: Text
  member schema_supported: Bool

fn decide(input: CanonicalInput) -> Result<Text,Text>
  requires input.previous == "ALL_PASS" else "collection_chain_broken"
  requires input.schema_supported else "schema_not_supported"
  return ok "CANONICAL"
