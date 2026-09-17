language T/2.0
module t.casulo.receipts
use t.casulo.dialogue
budget steps 256
budget deadline_ms 1000
schema version 1

record ReceiptInput
  member previous: Text
  member chain_valid: Bool

fn decide(input: ReceiptInput) -> Result<Text,Text>
  requires input.previous == "ANNOUNCE" else "dialogue_chain_broken"
  requires input.chain_valid else "receipt_chain_invalid"
  return ok "SEALED"
