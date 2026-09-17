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
  if input.segment_kind == "box_header"
    return ok "RAW_ONLY"
  else
    if input.segment_kind == "media_payload"
      if input.high_entropy
        return ok "RAW_ZLIB_SHUFFLE"
      else
        return ok "ALL"
    else
      return ok "ALL"

fn decide(input: CandidateEvidence) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.source_hash_valid else "source_hash_invalid"
  requires input.candidates_roundtrip else "candidate_roundtrip_failed"
  if input.segment_kind == "box_header"
    return ok "raw"
  else
    if input.has_delta8 and input.delta8_zlib_bytes <= input.raw_bytes and input.delta8_zlib_bytes <= input.zlib_bytes and input.delta8_zlib_bytes <= input.xor_prev_zlib_bytes and input.delta8_zlib_bytes <= input.shuffle4_zlib_bytes
      return ok "delta8-zlib"
    else
      if input.has_xor_prev and input.xor_prev_zlib_bytes <= input.raw_bytes and input.xor_prev_zlib_bytes <= input.zlib_bytes and input.xor_prev_zlib_bytes <= input.shuffle4_zlib_bytes
        return ok "xor-prev-zlib"
      else
        if input.has_shuffle4 and input.shuffle4_zlib_bytes <= input.raw_bytes and input.shuffle4_zlib_bytes <= input.zlib_bytes
          return ok "shuffle4-zlib"
        else
          if input.has_zlib and input.zlib_bytes <= input.raw_bytes
            return ok "zlib"
          else
            return ok "raw"
