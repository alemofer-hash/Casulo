# CASULO FAMILY RP0.1 — Day 2 local model

Date: 2026-09-18 to 2026-09-19
Branch: `rp0.1-family`
Gate result: `PASS_120_MINUTE_STABILITY`

## Frozen supply chain

The Day 2 runtime is the official llama.cpp Windows build `b10964`, commit
`b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, from stable release `v0.4.1`.
Both the CPU and Vulkan archives were checked against their frozen byte sizes,
SHA-256 values, and GitHub attestations. The runtime license is MIT.

The initial model repository was `Qwen/Qwen3-8B-GGUF`, frozen at revision
`7c41481f57cb95916b40956ab2f0b139b296d974` under Apache-2.0. Its official
Q4_K_M and Q5_K_M quantizations were downloaded, hashed and functionally
tested, but Qwen3 was rejected by the RAM gate.

The resource-fit repository is `Qwen/Qwen2.5-7B-Instruct-GGUF`, frozen at
revision `293ca9a10157b0e5fc5cb32af8b636a88bede891`. It is a 7.61B-parameter,
28-layer model with four KV heads, 32,768-token model context and an
8,192-token generation limit. The Casulo profile intentionally fixes context
to 8,192. The model card declares Apache-2.0; the canonical Apache license text
is frozen at SHA-256
`cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`.

| Candidate | Bytes | SHA-256 |
|---|---:|---|
| Qwen2.5 Q4_K_M shard 1 | 3,993,201,344 | `dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db` |
| Qwen2.5 Q4_K_M shard 2 | 689,872,288 | `539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a` |
| Qwen2.5 Q3_K_M | 3,808,391,072 | `a96b16179dc6cc9afdf0cf7a96a80c199cbd00b9be207c3465be21cb721cca5e` |
| Qwen2.5 Q2_K | 3,015,940,000 | `a0fc885ff014d73c02dcc4ad093f110c6dd4e0e308f84efe1accf078d364a87a` |

The local cache contains installation receipts, license texts, and an SPDX 2.3
SBOM. Model and runtime binaries remain outside Git; the repository
contains only frozen manifests, verification code, and evidence receipts.
Rollback is bounded to stopping the Casulo processes and removing only the
recorded Day 2 cache root after verifying no active process uses it.

## Local benchmark

`llama-bench` used 512 prompt tokens, 128 generated tokens, and three
repetitions per profile.

| Model/backend | Threads | GPU layers | Prompt tok/s | Generation tok/s |
|---|---:|---:|---:|---:|
| Qwen3 Q4_K_M CPU | 4 | 0 | 10.680344 | 4.455918 |
| Qwen3 Q4_K_M CPU | 6 | 0 | 11.021126 | 4.003627 |
| Qwen3 Q4_K_M CPU | 8 | 0 | 12.052548 | 3.175962 |
| Qwen3 Q4_K_M CPU | 10 | 0 | 10.824852 | 3.419877 |
| Qwen3 Q4_K_M Vulkan | 4 | 99 | 42.686264 | 3.513238 |
| Qwen3 Q5_K_M Vulkan | 4 | 99 | 43.223503 | 3.024295 |
| Qwen2.5 Q4_K_M CPU, F16 KV | 4 | 0 | 9.381538 | 4.118793 |
| Qwen2.5 Q4_K_M Vulkan, F16 KV | 4 | 99 | 56.858440 | 4.616591 |
| Qwen2.5 Q3_K_M CPU, F16 KV | 4 | 0 | 7.673893 | 4.680252 |
| Qwen2.5 Q3_K_M Vulkan, F16 KV | 4 | 99 | 67.775624 | 3.881103 |
| Qwen2.5 Q2_K CPU, F16 KV | 4 | 0 | 7.588271 | 5.233852 |
| Qwen2.5 Q2_K Vulkan, F16 KV | 4 | 99 | 57.843723 | 3.240349 |

Qwen2.5 Q2_K/Vulkan is the primary candidate because the larger Q4 profiles
crossed the RAM floor under the real notebook load. Vulkan processed prompt
tokens 7.62 times faster than CPU; CPU generated faster and passed its own
functional/resource calibration, so Q2_K/CPU is the operational fallback.
Q3_K_M remains a quality alternate only; it is not called a resource-qualified
fallback without a successful 120-minute gate.

## Memory-profile selection

The fastest raw profile was not accepted blindly:

- Qwen3 Q4/Vulkan with default F16 KV cache failed closed after 914.182 seconds;
  all 16 inferences were correct, but available RAM fell to 1,011,290,112
  bytes, below the explicit 1 GiB floor.
- Qwen3 Q4/CPU-4 with the default buffers failed on the first soak sample with only
  274,231,296 bytes available and a 7,721,091,072-byte working set.
- Qwen3 Q4/Vulkan with K/V Q8, batch 512 and ubatch 256 passed the short gate and
  reduced the final working set to 4,171,149,312 bytes, but its 1.19 GiB
  minimum RAM margin was not considered comfortable enough for the long gate.
- Qwen3 Q4/Vulkan with K Q8/V Q4 lasted 6,684.588 seconds and produced 111
  correct inferences, then failed closed at 963,756,032 available RAM.
- Qwen3 Q4/Vulkan with K/V Q4 failed immediately at 830,488,576 available RAM;
  quantizing Qwen3 KV further was therefore not accepted as a reliable fix.
- Qwen2.5 Q4 with quantized Q4 KV corrupted attention output. This was rejected,
  not relaxed. Restoring F16 KV produced correct Portuguese, JSON Schema, tool
  calling and stability output. Because Qwen2.5 has only four KV heads, the F16
  cache remained resource-compatible.
- Qwen2.5 Q4/F16-KV then passed the expanded functional matrix but failed its
  long gate after 2,187.217 seconds at 740,777,984 available RAM. Its 37 correct
  inferences and failure receipt are preserved; the floor was not relaxed.
- Qwen2.5 Q3/F16-KV passed the expanded short calibration with 3,769,315,328
  minimum available RAM, but was not promoted under the later, heavier notebook
  load and therefore remains an unqualified quality alternate.
- The selected Q2/Vulkan candidate uses F16 K/V cache, flash attention, batch
  128, ubatch 64, `--no-host`, four CPU threads, all model layers on `Vulkan0`,
  and the required 8,192-token context. Its expanded short calibration passed
  with 1,771,823,104 minimum available RAM, 3,676,065,792 maximum working set
  and 3,731,746,816 maximum process commit.
- Q2/CPU passed the same expanded matrix and short resource gate with
  2,096,164,864 minimum available RAM, 3,428,536,320 maximum working set and
  650,383,360 maximum process commit.

## Functional validation

Both selected Qwen2.5 Q2_K/Vulkan and fallback Q2_K/CPU passed:

- a complete Portuguese response;
- strict JSON Schema output with exact required values;
- an OpenAI-compatible function call with valid JSON arguments.
- a real Python code correction with the defect removed;
- client-side cancellation of a streaming response followed by a successful
  strict-JSON recovery request.

Receipts retain output hashes and token counts, not generated text. The server
argv is an array with `shell=False`; it binds `127.0.0.1`, disables the web UI,
and has no external URL or cloud dependency.

## Stability gate

The selected Qwen2.5 Q2_K/Vulkan profile completed one uninterrupted
7,201.414-second window against a requested 7,200 seconds. All 119 periodic
inferences passed and produced the expected output hash. The five pre-soak
functional probes also passed. There were zero inference, RAM, disk, startup,
or listener failures.

The minimum available RAM was 1,157,832,704 bytes (1.078 GiB), above the
1 GiB fail-closed floor. Maximum process working set was 3,686,653,952 bytes,
maximum peak working set was 3,705,835,520 bytes, and maximum process commit
was 3,733,880,832 bytes. Minimum free disk was 105,290,420,224 bytes
(98.06 GiB), above the permanent 30 GiB floor.

An earlier attempt was interrupted externally after 4,684.775 seconds. Its
receipt and counter CSV are preserved under `attempt1-interrupted` names with
their original bytes and hashes. Its elapsed time was not added to the passing
window.

The independent processor-counter trace contains 120 initialized samples from
12:14:04 to 14:13:06 local time. Performance Limit Flags were zero in all
samples and `% Performance Limit` never fell below 100. Actual-frequency
samples ranged from 1,167.385 to 2,114.485 MHz and averaged 1,496.079 MHz.
These counters are only a throttling proxy: absolute temperature remained
unavailable.

## Verification

- focused model/adoption/runtime tests: `23 passed in 5.39s`;
- complete Family + Product regression outside the WSH sandbox:
  `730 passed, 1 skipped in 176.59s`;
- broad repository regression: `1126 passed, 36 skipped, 59 subtests passed`;
  five VBS checks initially failed only because Windows Script Host settings
  were denied inside the sandbox and then passed outside it; five historical
  research tests were intentionally rejected by the repository's product
  guard because `CASULO_ENABLE_LEGACY_RESEARCH=1` was not authorized;
- final soak receipt SHA-256:
  `26a47447eb063ee4309693c88cdfffb52dd4875d6757d5f48fa3c7422f36c0ac`;
- final processor CSV SHA-256:
  `ad2517d90f22cec8aadac02579480c2e53936f581e15d9e94834f5cae5b17775`;
- processor-summary SHA-256:
  `8a6b69b6f6fd32dc1df5c1057eb12ae2f9c9f7859ef1d5009e3ce447c4013b12`.

## Explicit limitations and non-claims

- LibreHardwareMonitor 0.9.6 returned no current sensor rows. The installed
  HWiNFO64 instance did not expose shared memory and its licensed CLI logging
  did not produce a log. Temperature and thermal-throttling status are
  therefore `UNAVAILABLE`; no thermal-safety claim is made.
- The Day 2 model gate does not connect the real model to the Day 1 family
  gateway. That integration, streaming queue, cancellation, and backpressure
  belong to Day 3.
- No LAN listener, firewall rule, HTTPS certificate, paid API, cloud inference,
  ASR, TTS, or PWA was introduced.
- The 1 GiB available-RAM floor is a conservative operational guard for this
  notebook, not a claim that Windows paging was fully characterized.

## Next gate

Day 3 only: connect the selected loopback model adapter behind the Family
supervisor, add persistent streaming/cancellation/backpressure, and prove that
three clients remain serialized to one heavy generation without crossing the
resource floors.
