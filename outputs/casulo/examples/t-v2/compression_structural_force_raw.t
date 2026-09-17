language T/2.0
module compression.structural
budget steps 4096
budget deadline_ms 5000
schema version 1

record SegmentEvidence
  member segment_kind: Text
  member source_bytes: Int
  member high_entropy: Bool
  member cancelled: Bool

record CandidateEvidence
  member source_hash_valid: Bool
  member candidates_roundtrip: Bool
  member segment_kind: Text
  member raw_bytes: Int
  member has_zlib: Bool
  member zlib_bytes: Int
  member has_delta8: Bool
  member delta8_zlib_bytes: Int
  member has_xor_prev: Bool
  member xor_prev_zlib_bytes: Int
  member has_shuffle4: Bool
  member shuffle4_zlib_bytes: Int
  member cancelled: Bool

fn plan(input: SegmentEvidence) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.source_bytes > 0 else "empty_segment"
  return ok "RAW_ONLY"

fn decide(input: CandidateEvidence) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.source_hash_valid else "source_hash_invalid"
  requires input.candidates_roundtrip else "candidate_roundtrip_failed"
  return ok "raw"
