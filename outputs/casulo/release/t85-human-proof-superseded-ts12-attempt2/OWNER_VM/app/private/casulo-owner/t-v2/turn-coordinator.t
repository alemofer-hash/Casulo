language T/2.0
module owner.guide.turn_coordinator
budget steps 2048
budget deadline_ms 3000
schema version 1

record TurnInput
  member event_kind: Text
  member speech_detected: Bool
  member transcript_final: Bool
  member transcript_nonempty: Bool
  member tts_active: Bool
  member job_event_authenticated: Bool
  member cancelled: Bool

enum TurnDecision
  case BARGE_IN
  case COMMIT_FINAL
  case LISTEN
  case SHOW_PROGRESS
  case IGNORE

state committed_turns: Int = 0

fn coordinate(input: TurnInput) -> Result<Text,Text>
  cancel if input.cancelled
  if input.event_kind == "JOB_EVENT"
    requires input.job_event_authenticated else "progress_event_untrusted"
    return ok "SHOW_PROGRESS"
  else
    if input.speech_detected
      if input.tts_active
        return ok "BARGE_IN"
      else
        if input.transcript_final
          requires input.transcript_nonempty else "empty_final"
          set state.committed_turns = add(state.committed_turns, 1)
          return ok "COMMIT_FINAL"
        else
          return ok "LISTEN"
    else
      if input.event_kind == "TEXT_FINAL"
        requires input.transcript_final else "text_not_final"
        requires input.transcript_nonempty else "empty_final"
        set state.committed_turns = add(state.committed_turns, 1)
        return ok "COMMIT_FINAL"
      else
        return ok "IGNORE"
