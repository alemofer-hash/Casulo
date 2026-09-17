language T/2.0
module owner.native.sampling_policy
budget steps 256
budget deadline_ms 1000
schema version 1

record NativeSamplingInput
  member decoder_gate: Bool
  member token_index: Int
  member input_token_id: Int
  member logits_sha256: Text
  member blocks_completed: Int
  member greedy_candidate_id: Int
  member candidate_unpublished: Bool
  member policy_id: Text
  member previous_receipt_hash: Text
  member cancelled: Bool

fn decide(input: NativeSamplingInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.decoder_gate else "decoder_gate_failed"
  requires input.blocks_completed == 36 else "decoder_incomplete"
  requires input.candidate_unpublished else "late_publication_detected"
  requires input.policy_id == "greedy-incremental-v1" else "sampling_policy_mismatch"
  if input.token_index == 0
    requires input.input_token_id == 49242 else "first_input_token_mismatch"
    requires input.logits_sha256 == "4760c2d93598f80a1b3b44cdbcb20fe4785af71127c6fe544c2996c07035a509" else "first_logits_identity_mismatch"
    requires input.greedy_candidate_id == 6237 else "first_candidate_mismatch"
    requires input.previous_receipt_hash == "0000000000000000000000000000000000000000000000000000000000000000" else "first_receipt_predecessor_mismatch"
    return ok "PUBLISH_TOKEN"
  else
    if input.token_index == 1
      requires input.input_token_id == 6237 else "second_input_token_mismatch"
      requires input.logits_sha256 == "7d3054290d6283b90cc2e002f062a71aae0ae9dad0cfd3e1987e98c1457ee7f1" else "second_logits_identity_mismatch"
      requires input.greedy_candidate_id == 374 else "second_candidate_mismatch"
      requires len(input.previous_receipt_hash) == 64 else "second_receipt_predecessor_invalid"
      requires input.previous_receipt_hash != "0000000000000000000000000000000000000000000000000000000000000000" else "second_receipt_predecessor_missing"
      return ok "PUBLISH_TOKEN"
    else
      return error "token_index_unsupported"
