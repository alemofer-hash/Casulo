# TCAP v1

Status: normative for Casulo SO Research Preview 0.1.

## Container

All integers are unsigned little-endian. The 32-byte header is:

| Field | Type | Rule |
|---|---|---|
| magic | 4 bytes | `TCAP` |
| major/minor | u16/u16 | `1/0` |
| manifest length | u32 | 1..1 MiB |
| segment count | u32 | 1..64 |
| payload offset | u64 | 8-byte aligned and after manifest |
| file length | u64 | exact, at most 64 MiB |

The manifest is canonical UTF-8 JSON: sorted keys, no insignificant whitespace, no duplicate keys. Zero padding extends to the payload offset. Segment offsets are relative to the payload.

## Mandatory manifest

The manifest declares schema, target/ABI, entry point, compiler name/version/commit, resource contract, segment table, content hash and energy state. Unmeasured energy is exactly `{"status":"unavailable","joules":null}`.

Each segment declares name, relative offset, length, flags, alignment and SHA-256. Names are unique. Segments cannot overlap or exceed the file. W+X is forbidden. The entry point must fall inside one executable segment.

`content_sha256` hashes, in manifest order, the little-endian name length, name bytes, little-endian segment length and segment bytes for every segment. It is not self-referential.

## Resource and semantic contract

The embedded `casulo-resource-contract/1` declares bounded memory/arena, thread ceiling, semantic class, priority/deadline, determinism, precision, permissions, quality/equivalence, residual routing and optional energy budget. Unknown permissions or classes are rejected.

## Fail-closed parsing

The loader validates header bounds before JSON decoding and descriptor bounds before allocating/copying segments. Truncation, overflow-equivalent bounds, noncanonical or duplicate JSON, unknown versions, overlapping segments, invalid hashes, W+X, invalid entry points, excessive resources and permissions all result in `QUARANTINE`; no payload instruction may execute.

For the Research Preview learn workload, `target` is
`x86_64-casulo-none`, `abi` is `casulo-learn-context-sysv64/0.1`, and the
executable `code` segment is a position-independent raw image whose entry
offset is zero. The context layout and return statuses are frozen in
`docs/spec/LEARN_CONTEXT_ABI_V1.md`. A loader must reject an ABI it does not
implement rather than treating bytes as an arbitrary callable function.

The Research Preview package additionally contains the read-only `canary`
segment defined by `LEARN_CANARY_ABI_V1.md`. Its descriptor SHA-256 is covered
by normal TCAP integrity before the kernel interprets its bounded numerical
schema. It is a correctness fixture, never performance evidence.

## Research Preview kernel enforcement

The kernel derives a process-local syscall mask only after the resource
contract passes. `memory` does not grant a syscall; `console` grants bounded
console write, and EXIT is the mandatory system capability used to return to
the kernel. The learn process therefore receives mask `0x03`, not the kernel's
or G2 canary's broader mask. A known syscall missing from that mask returns
`-EPERM` and increments the permission audit counter; an unknown syscall
remains `-ENOSYS`.

For this frozen ABI, the kernel maps validated raw code RX and a separate
context/data page plus stack RW-NX under a process-specific CR3. SSE2 state and
round-to-nearest MXCSR are armed explicitly before entry. No host file,
dynamic linker, ELF metadata or physical block device participates at run
time.
