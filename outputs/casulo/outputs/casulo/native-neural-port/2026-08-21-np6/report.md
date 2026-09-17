# NP6 result

State: `NATIVE_ONE_COMPLETE_QWEN3_BLOCK_VALIDATED_36_BLOCKS_PENDING`.

One authentic Qwen3 token completed block zero inside Casulo Native. The guest
accounted for 100,925,440 MACs across seven quantized projections and compared
19 intermediate stages with an independent NumPy oracle. Three WHPX boots
returned the same scalar output SHA-256
`487179f486f1df8a132b66f7ef1f542a4f1a8768278dfe67d8e5bcaab77b0b51`
with mismatch mask zero.

The host Rust check additionally passed two token positions and 38/38 stages.
No later block, logits, sampling or model-derived output token was executed.
This is functional correctness evidence, not a performance, compression or
energy result.

Authoritative image:
`release/casulo-native-neural-port-np6-attempt-4.img`, SHA-256
`65a9b4360ef56355aececd16731ed33d4f508b82d6aff2043d75abc05624fef0`.

Next gate: all 36 blocks and logits with a bounded KV cache and independent
logit comparison. Output-token generation remains prohibited until NP8.
