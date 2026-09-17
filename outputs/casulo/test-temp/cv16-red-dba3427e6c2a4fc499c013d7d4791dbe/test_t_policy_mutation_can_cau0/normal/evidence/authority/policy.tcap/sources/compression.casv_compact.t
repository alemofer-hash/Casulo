language T/2.0
module compression.casv_compact
budget steps 4096
budget deadline_ms 5000
schema version 1

record TileCandidateEvidence
  member tile_index: Int
  member frame_index: Int
  member plane_index: Int
  member canonical_sha256: Text
  member exact_candidate_reconstruction: Bool
  member no_foreign_bitstream: Bool
  member dc_xor_bytes: Int
  member paeth_bytes: Int
  member direct_zlib_bytes: Int
  member raw_bytes: Int
  member cancelled: Bool

record ArchiveEvidence
  member exact_reconstruction: Bool
  member no_foreign_bitstream: Bool
  member source_bytes: Int
  member archive_bytes: Int
  member reference_zlib_bytes: Int
  member partition_exact: Bool
  member cancelled: Bool

fn decide(input: TileCandidateEvidence) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.tile_index >= 0 else "invalid_tile_index"
  requires input.frame_index >= 0 else "invalid_frame_index"
  requires input.plane_index >= 0 else "invalid_plane_index"
  requires input.exact_candidate_reconstruction else "tile_roundtrip_failed"
  requires input.no_foreign_bitstream else "foreign_video_bitstream_forbidden"
  requires input.dc_xor_bytes > 0 else "invalid_dc_cost"
  requires input.paeth_bytes > 0 else "invalid_paeth_cost"
  requires input.direct_zlib_bytes > 0 else "invalid_zlib_cost"
  requires input.raw_bytes > 0 else "empty_canonical_tile"
  if input.dc_xor_bytes <= input.paeth_bytes and input.dc_xor_bytes <= input.direct_zlib_bytes and input.dc_xor_bytes <= input.raw_bytes
    return ok "DC_XOR_ZLIB"
  else
    if input.paeth_bytes <= input.direct_zlib_bytes and input.paeth_bytes <= input.raw_bytes
      return ok "PAETH_ZLIB"
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
  requires input.reference_zlib_bytes > 0 else "empty_reference"
  requires input.partition_exact else "tile_partition_failed"
  if input.archive_bytes < input.reference_zlib_bytes
    return ok "ACCEPT_BEATS_REFERENCE"
  else
    if input.archive_bytes < input.source_bytes
      return ok "ACCEPT_RAW_ONLY"
    else
      return ok "REJECT"
