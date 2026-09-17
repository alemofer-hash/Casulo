# Casulo Reversible Transform IR v1

Status: implemented experimental contract  
Schema: `casulo.reversible-transform-ir/1.0`  
Scope: lossless structural transformation of one ISO BMFF/MP4 byte stream

## Purpose

This IR makes every claim of removal falsifiable. A source byte must belong to
exactly one ordered segment, and every segment must be reconstructible from a
content-addressed payload plus an explicitly named inverse. No model,
dictionary, policy or residual may be hidden outside the measured archive.

The source is represented as:

```text
source = base + dynamics + residual
```

This is an ordered partition, not numeric addition:

- **base** contains immutable format structure. In v1 this includes the exact
  top-level MP4 box headers and a read-only semantic description of nested
  boxes, sample tables and HEVC configuration;
- **dynamics** contains source bytes represented by an applied reversible
  transform;
- **residual** contains literal source bytes for which no allowed transform is
  smaller under the active T policy.

The concatenation of the inverse of every segment, in `index` order, must have
the source byte length and SHA-256 recorded in `source`.

## Invariants

1. Segment indices start at zero and are contiguous.
2. Segment source ranges start at byte zero, never overlap, never leave a gap
   and end at `source.bytes`.
3. Every segment has a SHA-256 of its original bytes.
4. Every payload path is exactly `payloads/<payload_sha256>.bin`.
5. The payload byte count equals the selected candidate byte count.
6. The transform and inverse identifiers are equal in v1.
7. A raw payload is `base` when it is a box header and `residual` otherwise.
8. A transformed payload is `dynamics`.
9. `base`, `dynamics` and `residual` are disjoint and their union contains all
   segment IDs.
10. The whole plan is canonical JSON and carries `plan_sha256`.
11. Every selected transform links to a productive T runtime receipt.
12. T receipts form a hash chain in segment order.
13. The T source, typed IR and TCAP identities are recorded and embedded.
14. The independent decoder rejects any unknown field set, path escape,
    duplicate member, broken hash, broken receipt or unsupported transform.

These invariants are enforced by both the encoder-side validator and a
separately implemented stdlib-only decoder.

## Source and structure

`source` contains:

```json
{
  "name": "input.mp4",
  "bytes": 123,
  "sha256": "..."
}
```

`base.structure` uses `casulo.mp4-hevc-structure/1.0`. Its parser:

- supports 32-bit, extended 64-bit, zero-to-parent and UUID box headers;
- validates every box against its parent boundary;
- limits nesting depth and total boxes;
- parses standard container prefixes and HEVC visual sample entries;
- parses `hvcC`, including profile, level, NAL length width and VPS/SPS/PPS;
- parses `stsz`, `stsc`, `stco` and `co64` with defensive count limits;
- maps chunk offsets to sample ranges when all required tables exist;
- reads only NAL headers from up to 64 uniformly spaced samples;
- records IRAP observations without claiming complete GOP analysis;
- samples at most three 64 KiB regions per top-level payload for Shannon
  entropy.

The semantic analysis is not used as a substitute for source bytes. It helps
choose and audit segmentation; the original information remains present in
the segment partition.

## Segmentation

Top-level MP4 headers are fixed base segments. Payloads up to 1 MiB remain one
segment. Larger payloads use deterministic content-defined boundaries:

```text
gear table seed = casulo-gear-v1
minimum         = 256 KiB
average         = 1 MiB
maximum         = 4 MiB
```

The boundary algorithm is content-sensitive and deterministic. It does not
promise equivalence to any third-party FastCDC implementation; the precise
gear table and recurrence in code are the normative definition.

## Reversible transform set

| ID | Forward | Inverse | Primitive boundary |
|---|---|---|---|
| `raw` | identity | identity | Python bytes |
| `zlib` | DEFLATE level 9 | zlib inflate | CPython zlib binding |
| `delta8-zlib` | byte delta modulo 256, then zlib | inflate, then prefix sum modulo 256 | Casulo prepass + zlib |
| `xor-prev-zlib` | XOR with previous original byte, then zlib | inflate, then causal XOR inverse | Casulo prepass + zlib |
| `shuffle4-zlib` | four byte-position lanes, then zlib | inflate, then lane interleave | Casulo prepass + zlib |

Each candidate is immediately inverted and compared byte-for-byte before its
size becomes evidence for T. A failed inverse terminates packing. The chosen
payload is hashed again and stored once by content hash.

V1 evaluates all candidates for non-header segments. This is correct but
computationally expensive. Entropy-directed candidate pruning and native SIMD
prepasses are explicit later optimizations; they cannot be introduced without
preserving causal T receipts and inverse tests.

## Segment record

Each segment includes:

```text
index, segment_id
source_offset, source_length, source_sha256
kind: box_header | metadata_payload | media_payload
lane: base | dynamics | residual
transform, inverse
payload_path, payload_sha256, payload_bytes
candidate_bytes
primitive
authority_receipt_hash
```

`candidate_bytes` exposes the counterfactual sizes seen by T. Runtime timing
for each forward candidate and inverse check is written separately to
`transform_measurements.jsonl`; wall-clock timing is evidence about the
implementation, not part of semantic identity.

## T authority

The default source is `examples/t-v2/compression_structural.t`. It crosses the
general T/2 pipeline:

```text
T source -> parser/AST -> semantic analysis -> typed IR -> module graph
         -> TCAP -> Rust T runtime -> decision receipt -> payload commit
```

T receives validated candidate evidence and returns the selected transform.
The encoder may execute primitive candidates but cannot replace, recompute or
ignore the T selection. An unavailable or rejected result fails closed.

The causal control source
`examples/t-v2/compression_structural_force_raw.t` differs only in policy. It
must produce a different source hash, typed IR hash, TCAP hash, receipt trace
and selected transform trace on compressible input. This mutation is a gate,
not a performance baseline.

## Archive contract

The transport is ZIP64 with `ZIP_STORED`; entry order, names and ZIP metadata
are deterministic, but runtime receipts contain monotonic timestamps and make
each execution artifact unique. The transport is not an additional compressor.
Required members are:

```text
plan.json
work-accounting.json
authority/policy.t
authority/receipts.jsonl
authority/decisions.jsonl
authority/tcap/**
payloads/<sha256>.bin
```

Archive size, not only payload size, is the final storage numerator. Source,
policy, TCAP, receipts, plan, indices and residual all count.

## Independent reconstruction

`src/casulo/compression/independent_structural.py` intentionally does not
import the encoder, transform implementation, T runtime or encoder-side IR
validator. It independently:

1. validates archive names and uniqueness;
2. validates canonical plan identity and partitions;
3. validates embedded TCAP section/source hashes;
4. validates the T receipt chain;
5. verifies every payload hash and length;
6. applies separately written bounded inverses;
7. verifies every reconstructed segment hash;
8. verifies final length and whole-source SHA-256;
9. publishes through a temporary file and atomic replace.

The standalone entrypoint is `tools/verify_casulo_structural.py`.

## Failure semantics

Missing metrics are never zero. Unknown codecs, malformed tables, incomplete
source coverage, unsupported schemas, stale receipts, duplicate ZIP members,
decompression beyond the declared segment length, hash mismatch and T refusal
all terminate with a nonzero result. Partial output is not promoted.

## Claim boundary

This contract proves that a transformation is explicit and reversible. It
does not prove that the transformation compresses well. In particular, HEVC
media payloads are already entropy-coded; large additional reductions require
a new causal representation whose full base, model and residual remain in the
numerator. A short probe is evidence of path execution only. A full-file
result requires a separately frozen campaign and independent reconstruction.
