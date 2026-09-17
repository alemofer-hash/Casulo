language T/2.0
module owner.native.creation_token_policy
budget steps 256
budget deadline_ms 1000
schema version 1

record NativeCreationTokenInput
  member decoder_gate: Bool
  member token_index: Int
  member max_tokens: Int
  member input_token_id: Int
  member logits_sha256: Text
  member blocks_completed: Int
  member greedy_candidate_id: Int
  member candidate_unpublished: Bool
  member model_sha256: Text
  member prompt_sha256: Text
  member policy_id: Text
  member previous_receipt_hash: Text
  member cancelled: Bool

fn decide(input: NativeCreationTokenInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.decoder_gate else "decoder_gate_failed"
  requires input.blocks_completed == 36 else "decoder_incomplete"
  requires input.token_index >= 0 else "negative_token_index"
  requires input.token_index < input.max_tokens else "token_budget_exhausted"
  requires input.max_tokens == 40 else "token_budget_mismatch"
  requires input.input_token_id >= 0 else "input_token_invalid"
  requires input.greedy_candidate_id >= 0 else "candidate_invalid"
  requires len(input.logits_sha256) == 64 else "logits_identity_invalid"
  requires len(input.model_sha256) == 64 else "model_identity_invalid"
  requires len(input.prompt_sha256) == 64 else "prompt_identity_invalid"
  requires input.candidate_unpublished else "late_publication_detected"
  requires input.policy_id == "greedy-creation-v1" else "sampling_policy_mismatch"
  if input.token_index == 0
    requires input.previous_receipt_hash == "0000000000000000000000000000000000000000000000000000000000000000" else "first_receipt_predecessor_mismatch"
    return ok "PUBLISH_TOKEN"
  else
    requires len(input.previous_receipt_hash) == 64 else "receipt_predecessor_invalid"
    requires input.previous_receipt_hash != "0000000000000000000000000000000000000000000000000000000000000000" else "receipt_predecessor_missing"
    return ok "PUBLISH_TOKEN"
