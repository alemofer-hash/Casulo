language T/2.0
module t.casulo.dialogue
use t.casulo.materialization
budget steps 256
budget deadline_ms 1000
schema version 1

record DialogueInput
  member previous: Text
  member progress_event_real: Bool

fn decide(input: DialogueInput) -> Result<Text,Text>
  requires input.previous == "PUBLISHED" else "materialization_chain_broken"
  requires input.progress_event_real else "invented_progress_denied"
  emit event "materialization_complete"
  return ok "ANNOUNCE"
