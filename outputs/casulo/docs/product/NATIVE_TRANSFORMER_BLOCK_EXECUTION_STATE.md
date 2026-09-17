# Casulo Native — NP6 one complete Qwen3 Transformer block

Date: 2026-08-21  
State: `NATIVE_ONE_COMPLETE_QWEN3_BLOCK_VALIDATED_36_BLOCKS_PENDING`

## Outcome

Casulo Native executed one authentic adopted-model token (`49242`, the first
token in `Casulo`) through every operation of Qwen3 block zero:

```text
Q6_K embedding
→ RMSNorm
→ Q4_K Q/K + Q6_K V projections
→ per-head Q/K RMSNorm
→ GGML adjacent-pair RoPE
→ grouped-query attention + bounded softmax
→ Q4_K output projection + residual
→ RMSNorm
→ Q4_K gate/up
→ SwiGLU
→ Q6_K down projection + residual
```

The guest compared 19 intermediate tensor summaries with a frozen independent
Python/NumPy oracle. All 19 passed; mismatch mask was zero. The final scalar
Rust output hash was
`487179f486f1df8a132b66f7ef1f542a4f1a8768278dfe67d8e5bcaab77b0b51`
in all three definitive boots.

This is the first complete Transformer block executed by the Casulo Native
runtime. It is not a complete decoder inference and did not compute block 1,
output RMSNorm, logits, sampling, or an output token.

## Adopted-model identity

- model: `Qwen3-4B-Q4_K_M.gguf`;
- bytes: `2,497,280,256`;
- SHA-256: `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`;
- GGUF v3, architecture `qwen3`;
- embedding `2560`, FFN `9728`, 32 Q heads, 8 KV heads;
- key/value head dimension `128`;
- RMS epsilon approximately `1e-6`, RoPE base `1,000,000`;
- model remained outside the repository and unchanged.

## Block-zero tensor inventory

| Tensor | Dimensions | Type | Absolute offset | Bytes |
| --- | ---: | ---: | ---: | ---: |
| `attn_k.weight` | 2560×1024 | Q4_K | 325032192 | 1474560 |
| `attn_k_norm.weight` | 128 | F32 | 326506752 | 512 |
| `attn_norm.weight` | 2560 | F32 | 326507264 | 10240 |
| `attn_output.weight` | 4096×2560 | Q4_K | 326517504 | 5898240 |
| `attn_q.weight` | 2560×4096 | Q4_K | 332415744 | 5898240 |
| `attn_q_norm.weight` | 128 | F32 | 338313984 | 512 |
| `attn_v.weight` | 2560×1024 | Q6_K | 338314496 | 2150400 |
| `ffn_down.weight` | 9728×2560 | Q6_K | 340464896 | 20428800 |
| `ffn_gate.weight` | 2560×9728 | Q4_K | 360893696 | 14008320 |
| `ffn_norm.weight` | 2560 | F32 | 374902016 | 10240 |
| `ffn_up.weight` | 2560×9728 | Q4_K | 374912256 | 14008320 |

Per-tensor raw hashes are sealed in `block0-oracle-attempt-3.json`.

## Work receipt

The Native scientific unit was one complete block position:

- 7 quantized matvec calls;
- 394,240 quantized blocks decoded;
- 63,866,880 weight bytes consumed by the matvecs;
- 100,925,440 multiply-accumulates;
- 32 attention scores/weights for context length 1;
- 19 intermediate stages compared;
- activation arena: 259,328 bytes;
- 275 bounded prefetch regions loaded, 550 fw_cfg DMA operations;
- 72,072,000 bytes loaded including GGUF metadata, embedding and cache-region
  granularity.

The host Rust gate additionally executed both token positions `[49242, 8763]`
through the full block and compared 38/38 stages. That stronger host-only check
exercises causal context length 2. The Native NP6 claim remains the strict
one-token, one-block result above; multi-token KV behavior remains an NP7 gate.

## Oracle and tolerances

The oracle independently parses the GGUF and vectorizes Q4_K/Q6_K decoding in
NumPy 2.3.5. The Native runtime uses scalar Rust/no_std accumulation. Bit
identity is therefore not required between those two implementations.

Frozen comparison limits:

- sum and squared-L2: max(`0.001`, `0.05%` relative);
- minimum/maximum: max(`0.0001`, `0.05%` relative);
- value counts: exact;
- final output hash between scalar host Rust and Native Rust: exact.

The host comparison passed 38/38 stages. The Native comparison passed the
strict NP6 prefix of 19/19 stages and reproduced the scalar hash exactly.

## I/O and memory correction

The first guest attempts exposed a real transport bottleneck: a 4 KiB fw_cfg
DMA cache caused tens of thousands of VM exits. NP6 introduced a bounded,
physically contiguous 256 KiB read-only prefetch region. The model still stays
outside the heap; no host path, network endpoint, USB or physical block device
is available to the guest.

The activation arena uses 259,328 bytes. Together with the 256 KiB prefetch
cache it remains below the existing 2 MiB kernel heap. No full-model residency
or copy was introduced.

## Preserved failures

The following artifacts are evidence, not passing results:

- `block0-oracle.json`: wrong rotate-half assumption for the GGML RoPE ABI;
- `block0-oracle-attempt-2.json`: corrected RoPE, incomplete intermediate set;
- `qemu-smoke-whpx.json`: two-token guest scope timed out at 120 s;
- `qemu-smoke-tcg.json`: two-token guest scope timed out at 300 s;
- `qemu-smoke-tcg-prefetch.json`: two-token scope still too slow under TCG;
- `qemu-smoke-tcg-one-token.json`: strict scope timed out under TCG;
- `qemu-smoke-whpx-one-token.json`: block passed, but inherited validator still
  demanded the superseded `NOT_EXECUTED` marker;
- `qemu-definitive-3boots.json`: 3/3 technical passes, but the validator kept a
  stale pre-removal boolean.

`qemu-definitive-3boots-attempt-2.json` is authoritative and passed.

## Validation

- Rust `casulo-native-model`: 14/14 tests PASS;
- focused Python product suite: 31/31 PASS after using workspace-local temp;
- host independent comparison: 38/38 PASS;
- Native definitive WHPX boots: 3/3 PASS, one unique output hash;
- missing model and truncated model: rejected;
- malformed matrix shape, position 2 RoPE and context 3 at NP6: rejected;
- image and model hashes unchanged across the definitive run;
- guest network OFF; physical device writes: none;
- performance and energy: not measured.

## Authoritative artifacts

- `release/casulo-native-neural-port-np6-attempt-4.img`;
- `release/casulo-native-neural-port-np6-attempt-4.manifest.json`;
- `outputs/casulo/native-neural-port/2026-08-21-np6/block0-oracle-attempt-3.json`;
- `outputs/casulo/native-neural-port/2026-08-21-np6/host-verification/block0-comparison.json`;
- `outputs/casulo/native-neural-port/2026-08-21-np6/qemu-definitive-3boots-attempt-2.json`.

## Next gate

`NP7_ALL_36_BLOCKS_AND_LOGITS` must add a general RoPE frequency path, bounded
KV cache, cancellation/watchdog at block boundaries, all 36 blocks, final
RMSNorm and logits. Logits must match an independent oracle before sampling.
No output token is authorized until NP8.

