language T/2.0
module compression.casv
budget steps 4096
budget deadline_ms 5000
schema version 1

record CandidateEvidence
  member segment_index: Int
  member canonical_sha256: Text
  member generative_candidate_available: Bool
  member exact_generative_reconstruction: Bool
  member no_foreign_bitstream: Bool
  member generative_bytes: Int
  member direct_zlib_bytes: Int
  member raw_bytes: Int
  member cancelled: Bool

record ArchiveEvidence
  member exact_reconstruction: Bool
  member no_foreign_bitstream: Bool
  member source_bytes: Int
  member archive_bytes: Int
  member partition_exact: Bool
  member cancelled: Bool

fn decide(input: CandidateEvidence) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.segment_index >= 0 else "invalid_segment_index"
  requires input.no_foreign_bitstream else "foreign_video_bitstream_forbidden"
  requires input.raw_bytes > 0 else "empty_canonical_media"
  if input.generative_candidate_available
    requires input.exact_generative_reconstruction else "generative_roundtrip_failed"
    if input.generative_bytes <= input.direct_zlib_bytes and input.generative_bytes <= input.raw_bytes
      return ok "GENERATIVE_EXACT"
    else
      if input.direct_zlib_bytes <= input.raw_bytes
        return ok "CANONICAL_ZLIB"
      else
        return ok "CANONICAL_RAW"
  else
    if input.direct_zlib_bytes <= input.raw_bytes
      return ok "CANONICAL_ZLIB"
    else
      return ok "CANONICAL_RAW"

fn judge(input: ArchiveEvidence) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.exact_reconstruction else "independent_reconstruction_failed"
  requires input.no_foreign_bitstream else "foreign_video_bitstream_forbidden"
  requires input.source_bytes > 0 else "empty_canonical_media"
  requires input.archive_bytes > 0 else "empty_archive"
  requires input.partition_exact else "base_dynamics_residual_partition_failed"
  if input.archive_bytes < input.source_bytes
    return ok "ACCEPT"
  else
    return ok "REJECT"
