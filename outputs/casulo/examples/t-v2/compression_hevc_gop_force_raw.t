language T/2.0
module compression.hevc_gop
budget steps 4096
budget deadline_ms 5000
schema version 1

record NALPlanEvidence
  member nal_class: Text
  member source_bytes: Int
  member high_entropy: Bool
  member reference_available: Bool
  member cancelled: Bool

record NALCandidateEvidence
  member source_hash_valid: Bool
  member candidates_roundtrip: Bool
  member raw_bytes: Int
  member has_zlib: Bool
  member zlib_bytes: Int
  member has_xor_reference: Bool
  member xor_reference_bytes: Int
  member cancelled: Bool

record ArchiveCostEvidence
  member exact_reconstruction: Bool
  member source_bytes: Int
  member archive_bytes: Int
  member base_source_bytes: Int
  member dynamics_source_bytes: Int
  member residual_source_bytes: Int
  member partition_exact: Bool
  member cancelled: Bool

fn plan(input: NALPlanEvidence) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.source_bytes > 0 else "empty_nal_body"
  return ok "RAW_ONLY"

fn decide(input: NALCandidateEvidence) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.source_hash_valid else "source_hash_invalid"
  requires input.candidates_roundtrip else "candidate_roundtrip_failed"
  return ok "raw"

fn judge(input: ArchiveCostEvidence) -> Result<Text,Text>
  cancel if input.cancelled
  requires input.exact_reconstruction else "independent_reconstruction_failed"
  requires input.source_bytes > 0 else "empty_source"
  requires input.archive_bytes > 0 else "empty_archive"
  requires input.partition_exact else "partition_accounting_failed"
  if input.archive_bytes < input.source_bytes
    return ok "ACCEPT"
  else
    return ok "REJECT"
