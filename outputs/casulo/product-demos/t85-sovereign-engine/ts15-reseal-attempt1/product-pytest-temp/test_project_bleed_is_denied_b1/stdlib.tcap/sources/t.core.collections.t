language T/2.0
module t.core.collections
use t.core.result
budget steps 1024
budget deadline_ms 1000
schema version 1

record CollectionInput
  member previous: Text
  member statuses: List<Text,64>

fn decide(input: CollectionInput) -> Result<Text,Text>
  requires input.previous == "PASS" else "result_chain_broken"
  for status in input.statuses limit 64
    requires status == "PASS" else "collection_contains_non_pass"
  return ok "ALL_PASS"
