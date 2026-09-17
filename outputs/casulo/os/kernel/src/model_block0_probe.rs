//! NP6 complete execution of one adopted-model token through Qwen3 block 0.
//!
//! This module is owner-only, offline, read-only and bounded. It does not run
//! block 1, output normalization, logits, sampling, or publish an output token.

extern crate alloc;

use alloc::vec;
use casulo_native_model::{
    Error as ModelError, NP6_CONTEXT_TOKENS, PagedQwenGguf, QWEN3_EMBEDDING_LENGTH,
    QWEN3_FFN_LENGTH, QWEN3_KV_LENGTH, QWEN3_Q_HEADS, QWEN3_Q_LENGTH, QwenBlock0Receipt,
    QwenBlock0Workspace, execute_qwen3_block0_np6, grouped_query_attention_np6, quantized_matvec,
    rope_qwen3_np6_in_place,
};
use sha2::{Digest, Sha256};

use crate::fw_cfg::{self, ReadStats};
use crate::memory::MemorySummary;
use crate::model_block0_oracle::{self, OracleReceipt};
use crate::model_paged_probe::EXPECTED_MODEL_BYTES;

const EXPECTED_OUTPUT_SHA256: [u8; 32] = [
    0x48, 0x71, 0x79, 0xf4, 0x86, 0xf1, 0xdf, 0x8a, 0x13, 0x2b, 0x66, 0xf7, 0xef, 0x1f, 0x54, 0x2a,
    0x4f, 0x1a, 0x87, 0x68, 0x27, 0x8d, 0xfe, 0x67, 0xd8, 0xe5, 0xbc, 0xaa, 0xb7, 0x7b, 0x0b, 0x51,
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Reject {
    Transport(fw_cfg::Reject),
    Model(ModelError),
    WorkAccounting,
    Oracle,
    OutputHash,
    Adversarial,
}

impl From<fw_cfg::Reject> for Reject {
    fn from(value: fw_cfg::Reject) -> Self {
        Self::Transport(value)
    }
}

impl From<ModelError> for Reject {
    fn from(value: ModelError) -> Self {
        Self::Model(value)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Receipt {
    pub block: QwenBlock0Receipt,
    pub oracle: OracleReceipt,
    pub output_sha256: [u8; 32],
    pub arena_bytes: u32,
    pub shape_mutation_rejected: bool,
    pub wider_rope_rejected: bool,
    pub wider_context_rejected: bool,
    pub stats: ReadStats,
}

pub fn run(memory: &mut MemorySummary) -> Result<Receipt, Reject> {
    let mut source = fw_cfg::ModelFile::open(memory, EXPECTED_MODEL_BYTES)?;
    let gguf = PagedQwenGguf::parse(&mut source)?;
    let tensors = gguf.block0_tensors(&mut source)?;
    let embedding = gguf.tensor(&mut source, "token_embd.weight")?;

    // One explicit bounded activation arena assembled from owned Vec regions.
    // Total is reported and remains far below the two-MiB kernel heap.
    let mut state = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut norm = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut query = vec![0.0; QWEN3_Q_LENGTH];
    let mut key_cache = vec![0.0; NP6_CONTEXT_TOKENS * QWEN3_KV_LENGTH];
    let mut value_cache = vec![0.0; NP6_CONTEXT_TOKENS * QWEN3_KV_LENGTH];
    let mut attention_context = vec![0.0; QWEN3_Q_LENGTH];
    let mut projected = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut residual = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut gate = vec![0.0; QWEN3_FFN_LENGTH];
    let mut up = vec![0.0; QWEN3_FFN_LENGTH];
    let mut activated = vec![0.0; QWEN3_FFN_LENGTH];
    let mut down = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut attention_weights = vec![0.0; QWEN3_Q_HEADS * NP6_CONTEXT_TOKENS];
    let mut attn_norm_weight = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut query_norm_weight = vec![0.0; 128];
    let mut key_norm_weight = vec![0.0; 128];
    let mut ffn_norm_weight = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut outputs = vec![0.0; NP6_CONTEXT_TOKENS * QWEN3_EMBEDDING_LENGTH];
    let mut quantized_input = vec![0.0; QWEN3_FFN_LENGTH];
    let arena_values = state.len()
        + norm.len()
        + query.len()
        + key_cache.len()
        + value_cache.len()
        + attention_context.len()
        + projected.len()
        + residual.len()
        + gate.len()
        + up.len()
        + activated.len()
        + down.len()
        + attention_weights.len()
        + attn_norm_weight.len()
        + query_norm_weight.len()
        + key_norm_weight.len()
        + ffn_norm_weight.len()
        + outputs.len()
        + quantized_input.len();
    let arena_bytes = u32::try_from(arena_values.checked_mul(4).ok_or(ModelError::Bounds)?)
        .map_err(|_| ModelError::Bounds)?;
    if arena_bytes > 512 * 1024 {
        return Err(Reject::WorkAccounting);
    }

    let mut workspace = QwenBlock0Workspace {
        state: &mut state,
        norm: &mut norm,
        query: &mut query,
        key_cache: &mut key_cache,
        value_cache: &mut value_cache,
        attention_context: &mut attention_context,
        projected: &mut projected,
        residual: &mut residual,
        gate: &mut gate,
        up: &mut up,
        activated: &mut activated,
        down: &mut down,
        attention_weights: &mut attention_weights,
        attn_norm_weight: &mut attn_norm_weight,
        query_norm_weight: &mut query_norm_weight,
        key_norm_weight: &mut key_norm_weight,
        ffn_norm_weight: &mut ffn_norm_weight,
        outputs: &mut outputs,
        quantized_input: &mut quantized_input,
    };
    let block = execute_qwen3_block0_np6(
        &mut source,
        &gguf,
        tensors,
        embedding,
        [49_242, 8_763],
        1,
        &mut workspace,
    )?;
    if block.tokens_completed != 1
        || block.descriptors_scanned != 398
        || block.work.matvec_calls != 7
        || block.work.quantized_blocks != 394_240
        || block.work.weight_bytes_read != 63_866_880
        || block.work.multiply_accumulates != 100_925_440
        || block.attention_scores != 32
    {
        return Err(Reject::WorkAccounting);
    }
    let oracle = model_block0_oracle::verify(&block);
    if !oracle.passed_for(block.tokens_completed) {
        return Err(Reject::Oracle);
    }
    let mut digest = Sha256::new();
    for value in workspace.outputs[..QWEN3_EMBEDDING_LENGTH].iter() {
        digest.update(value.to_le_bytes());
    }
    let output_sha256: [u8; 32] = digest.finalize().into();
    if output_sha256 != EXPECTED_OUTPUT_SHA256 {
        return Err(Reject::OutputHash);
    }

    // Negative controls mutate policy/shape only. They must reject before an
    // additional expensive projection or any result publication.
    let mut malformed = tensors.attn_q;
    malformed.dimensions[0] -= 1;
    let shape_mutation_rejected =
        quantized_matvec(&mut source, malformed, workspace.norm, workspace.query).is_err();
    let wider_rope_rejected = rope_qwen3_np6_in_place(
        workspace.query,
        QWEN3_Q_HEADS,
        2,
        gguf.config().rope_frequency_base,
    )
    .is_err();
    let wider_context_rejected = grouped_query_attention_np6(
        workspace.query,
        workspace.key_cache,
        workspace.value_cache,
        QWEN3_Q_HEADS,
        8,
        128,
        3,
        workspace.attention_context,
        workspace.attention_weights,
    )
    .is_err();
    if !shape_mutation_rejected || !wider_rope_rejected || !wider_context_rejected {
        return Err(Reject::Adversarial);
    }

    Ok(Receipt {
        block,
        oracle,
        output_sha256,
        arena_bytes,
        shape_mutation_rejected,
        wider_rope_rejected,
        wider_context_rejected,
        stats: source.stats(),
    })
}
