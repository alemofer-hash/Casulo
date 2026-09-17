language T/2.0
module owner.native.sampling_policy
budget steps 256
budget deadline_ms 1000
schema version 1

record NativeSamplingInput
  member decoder_gate: Bool
  member logits_sha256: Text
  member blocks_completed: Int
  member greedy_candidate_id: Int
  member candidate_unpublished: Bool
  member policy_id: Text
  member cancelled: Bool

fn decide(input: NativeSamplingInput) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.decoder_gate else "decoder_gate_failed"
  requires input.logits_sha256 == "4760c2d93598f80a1b3b44cdbcb20fe4785af71127c6fe544c2996c07035a509" else "logits_identity_mismatch"
  requires input.blocks_completed == 36 else "decoder_incomplete"
  requires input.greedy_candidate_id == 6237 else "candidate_mismatch"
  requires input.candidate_unpublished else "late_publication_detected"
  requires input.policy_id == "greedy-debug-v1" else "sampling_policy_mismatch"
  return ok "PUBLISH_GREEDY"
