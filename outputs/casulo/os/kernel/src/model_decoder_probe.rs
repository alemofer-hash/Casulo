//! NP7 complete one-token Qwen3 decoder pass inside the Casulo kernel.
//!
//! The admitted GGUF remains external and read-only through fw_cfg. This gate
//! executes all 36 transformer blocks, output normalization and tied output
//! projection. It verifies one candidate token but deliberately does not
//! sample or publish it; publication belongs to the later T policy gate.

extern crate alloc;

use alloc::{string::String, vec};
use casulo_native_model::{
    BlockWorkReceipt, DecoderBlockWatchdog, Error as ModelError, PagedQwenGguf,
    QWEN3_EMBEDDING_LENGTH, QWEN3_FFN_LENGTH, QWEN3_KV_LENGTH, QWEN3_Q_HEADS, QWEN3_Q_LENGTH,
    QwenBlock0Workspace, WatchdogError, execute_qwen3_block_np7, quantized_matvec, read_f32_vector,
    read_q6_k_embedding_row, rms_norm,
};
use core::fmt::Write;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use crate::fw_cfg::{self, ReadStats};
use crate::memory::MemorySummary;
use crate::model_paged_probe::EXPECTED_MODEL_BYTES;
use crate::serial::Serial;
use crate::tcap_v2;

const INPUT_TOKEN_ID: u32 = 49_242;
const EXPECTED_BLOCKS: u32 = 36;
const EXPECTED_MATVEC_CALLS: u32 = 253;
const EXPECTED_QUANTIZED_BLOCKS: u64 = 15_712_000;
const EXPECTED_WEIGHT_BYTES_READ: u64 = 2_490_539_520;
const EXPECTED_MULTIPLY_ACCUMULATES: u64 = 4_022_272_000;
const EXPECTED_ATTENTION_SCORES: u32 = EXPECTED_BLOCKS * QWEN3_Q_HEADS as u32;
const EXPECTED_GREEDY_TOKEN_ID: u32 = 6_237;
const EXPECTED_SECOND_GREEDY_TOKEN_ID: u32 = 374;
#[cfg(casulo_native_model_resident)]
const MAX_ARENA_BYTES: u32 = 2 * 1_024 * 1_024;
#[cfg(not(casulo_native_model_resident))]
const MAX_ARENA_BYTES: u32 = 1_024 * 1_024;
const MAX_CANDIDATE_TEXT_BYTES: usize = 32;
const ZERO_RECEIPT_HASH: &str = "0000000000000000000000000000000000000000000000000000000000000000";
// The legacy PIT is a boot-integrity source, not a dependable latency clock
// while WHPX executes a long SIMD hot path. Use the invariant TSC already
// admitted by the Native timing contract for this bounded input window.
const CANCEL_WINDOW_TSC_CYCLES: u64 = 3_000_000_000;

const EXPECTED_HIDDEN_CHAIN_SHA256: [u8; 32] = [
    0x9b, 0x1a, 0x77, 0x5c, 0xf3, 0x15, 0x50, 0x60, 0xf8, 0xd8, 0xe1, 0x89, 0x88, 0x22, 0xa6, 0x84,
    0xdb, 0x5e, 0x18, 0x48, 0xa6, 0x01, 0xe6, 0xc6, 0x0a, 0x37, 0xb7, 0xa8, 0xb8, 0xb6, 0x07, 0x9b,
];
const EXPECTED_LOGITS_SHA256: [u8; 32] = [
    0x47, 0x60, 0xc2, 0xd9, 0x35, 0x98, 0xf8, 0x0a, 0x1b, 0x3b, 0x44, 0xcd, 0xbc, 0xb2, 0x0f, 0xe4,
    0x78, 0x5a, 0xf7, 0x11, 0x27, 0xc6, 0xfe, 0x54, 0x4c, 0x29, 0x96, 0xc0, 0x70, 0x35, 0xa5, 0x09,
];
const EXPECTED_SECOND_HIDDEN_CHAIN_SHA256: [u8; 32] = [
    0x1b, 0x89, 0xf4, 0xba, 0xa2, 0x29, 0x8d, 0x9e, 0xad, 0x2e, 0x7c, 0xb5, 0x79, 0x4e, 0x51, 0xd5,
    0x9b, 0x37, 0xbb, 0xf0, 0x98, 0x57, 0x93, 0x1f, 0x28, 0x4d, 0xe3, 0x6d, 0x9a, 0xca, 0x31, 0xdc,
];
const EXPECTED_SECOND_LOGITS_SHA256: [u8; 32] = [
    0x7d, 0x30, 0x54, 0x29, 0x0d, 0x62, 0x83, 0xb9, 0x0c, 0xc2, 0xe0, 0x02, 0xf0, 0x62, 0xa7, 0x1a,
    0xae, 0x0a, 0xe9, 0xda, 0xd0, 0xcf, 0xd3, 0xe1, 0x98, 0x7e, 0x98, 0xc1, 0x45, 0x7e, 0xe7, 0xf1,
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Reject {
    Transport(fw_cfg::Reject),
    Model(ModelError),
    Watchdog(WatchdogError),
    WorkAccounting,
    HiddenHash,
    LogitsHash,
    Candidate,
    Arena,
    CancellationControl,
    SamplingPolicy,
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

impl From<WatchdogError> for Reject {
    fn from(value: WatchdogError) -> Self {
        Self::Watchdog(value)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Receipt {
    pub input_token_id: u32,
    pub blocks_completed: u32,
    pub work: BlockWorkReceipt,
    pub attention_scores: u32,
    pub hidden_chain_sha256: [u8; 32],
    pub logits_sha256: [u8; 32],
    pub greedy_candidate_token_id: u32,
    pub greedy_candidate_logit_bits: u32,
    pub greedy_candidate_text: [u8; MAX_CANDIDATE_TEXT_BYTES],
    pub greedy_candidate_text_len: u8,
    pub arena_bytes: u32,
    pub cancellation_rejected_before_work: bool,
    pub candidate_published: bool,
    pub sampling_gate: bool,
    pub sampling_tokens_authorized: u32,
    pub sampling_steps_total: u64,
    pub sampling_tcap_hash: [u8; 32],
    pub sampling_receipt_chain_tail: [u8; 32],
    pub cancelled_after_token_boundary: bool,
    pub incremental_tokens_completed: u32,
    pub second_candidate_token_id: u32,
    pub second_hidden_chain_sha256: [u8; 32],
    pub second_logits_sha256: [u8; 32],
    pub second_candidate_text: [u8; MAX_CANDIDATE_TEXT_BYTES],
    pub second_candidate_text_len: u8,
    pub kv_values: u32,
    pub second_candidate_published: bool,
    pub stats: ReadStats,
}

fn hex32(value: &[u8; 32]) -> String {
    let mut output = String::with_capacity(64);
    for byte in value {
        let _ = write!(output, "{byte:02x}");
    }
    output
}

fn parse_hex32(value: &str) -> Result<[u8; 32], Reject> {
    if value.len() != 64 {
        return Err(Reject::SamplingPolicy);
    }
    let mut output = [0u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = (pair[0] as char)
            .to_digit(16)
            .ok_or(Reject::SamplingPolicy)? as u8;
        let low = (pair[1] as char)
            .to_digit(16)
            .ok_or(Reject::SamplingPolicy)? as u8;
        output[index] = (high << 4) | low;
    }
    Ok(output)
}

#[allow(clippy::too_many_arguments)]
fn authorize_and_stream_token(
    policy: &[u8],
    serial: &mut Serial,
    token_index: u32,
    input_token_id: u32,
    logits_sha256: &[u8; 32],
    candidate_id: u32,
    candidate_text: &[u8],
    previous_receipt_hash: &str,
) -> Result<tcap_v2::NativeProbe, Reject> {
    let payload = json!({
        "decoder_gate": true,
        "token_index": token_index,
        "input_token_id": input_token_id,
        "logits_sha256": hex32(logits_sha256),
        "blocks_completed": EXPECTED_BLOCKS,
        "greedy_candidate_id": candidate_id,
        "candidate_unpublished": true,
        "policy_id": "greedy-incremental-v1",
        "previous_receipt_hash": previous_receipt_hash,
        "cancelled": false,
    });
    let probe = tcap_v2::execute_with_payload(
        policy,
        &payload,
        if previous_receipt_hash == ZERO_RECEIPT_HASH {
            None
        } else {
            Some(previous_receipt_hash)
        },
    )
    .map_err(|_| Reject::SamplingPolicy)?;
    if probe.input_payload != payload
        || probe.result.get("kind").and_then(Value::as_str) != Some("ok")
        || probe.result.get("value").and_then(Value::as_str) != Some("PUBLISH_TOKEN")
    {
        return Err(Reject::SamplingPolicy);
    }
    let _ = writeln!(serial, "CASULO_NATIVE_STREAM_TOKEN_{token_index}_BEGIN");
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_STREAM_TOKEN_{token_index}_POLICY_TCAP_HASH={}",
        probe.tcap_hash
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_STREAM_TOKEN_{token_index}_POLICY_RECEIPT={}",
        probe.receipt
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_STREAM_TOKEN_{token_index}_ID={candidate_id}"
    );
    let _ = write!(serial, "CASULO_NATIVE_STREAM_TOKEN_{token_index}_TEXT_HEX=");
    for byte in candidate_text {
        let _ = write!(serial, "{byte:02x}");
    }
    let _ = writeln!(serial);
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_STREAM_TOKEN_{token_index}_PUBLICATION=PASS"
    );
    let _ = writeln!(serial, "CASULO_NATIVE_STREAM_TOKEN_{token_index}_END");
    Ok(probe)
}

fn cancellation_requested_at_boundary(serial: &mut Serial) -> bool {
    let start = unsafe { core::arch::x86_64::_rdtsc() };
    let _ = writeln!(serial, "CASULO_NATIVE_STREAM_CANCEL_WINDOW=OPEN");
    while unsafe { core::arch::x86_64::_rdtsc() }.wrapping_sub(start) < CANCEL_WINDOW_TSC_CYCLES {
        if let Some(byte) = serial.try_read_byte() {
            if matches!(byte, 0x03 | 0x1b | b'c' | b'C') {
                let _ = writeln!(serial, "CASULO_NATIVE_STREAM_CANCEL=ACCEPTED");
                return true;
            }
        }
        core::hint::spin_loop();
    }
    let _ = writeln!(serial, "CASULO_NATIVE_STREAM_CANCEL_WINDOW=CLOSED");
    false
}

fn add_work(total: &mut BlockWorkReceipt, observed: BlockWorkReceipt) -> Result<(), Reject> {
    total.matvec_calls = total
        .matvec_calls
        .checked_add(observed.matvec_calls)
        .ok_or(Reject::WorkAccounting)?;
    total.quantized_blocks = total
        .quantized_blocks
        .checked_add(observed.quantized_blocks)
        .ok_or(Reject::WorkAccounting)?;
    total.weight_bytes_read = total
        .weight_bytes_read
        .checked_add(observed.weight_bytes_read)
        .ok_or(Reject::WorkAccounting)?;
    total.multiply_accumulates = total
        .multiply_accumulates
        .checked_add(observed.multiply_accumulates)
        .ok_or(Reject::WorkAccounting)?;
    Ok(())
}

pub fn run(
    memory: &mut MemorySummary,
    serial: &mut Serial,
    sampling_policy: Option<&[u8]>,
) -> Result<Receipt, Reject> {
    let admission_started = unsafe { core::arch::x86_64::_rdtsc() };
    let _ = writeln!(serial, "CASULO_NATIVE_DECODER_ADMISSION=BEGIN");
    #[cfg(casulo_native_model_resident)]
    let mut source = fw_cfg::ModelFile::open_resident(memory, EXPECTED_MODEL_BYTES)?;
    #[cfg(not(casulo_native_model_resident))]
    let mut source = fw_cfg::ModelFile::open(memory, EXPECTED_MODEL_BYTES)?;
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_DECODER_ADMISSION_CYCLES={}",
        unsafe { core::arch::x86_64::_rdtsc() }.wrapping_sub(admission_started)
    );
    let parse_started = unsafe { core::arch::x86_64::_rdtsc() };
    let gguf = PagedQwenGguf::parse(&mut source)?;
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_DECODER_PARSE_CYCLES={}",
        unsafe { core::arch::x86_64::_rdtsc() }.wrapping_sub(parse_started)
    );
    let config = gguf.config();
    if config.block_count != EXPECTED_BLOCKS {
        return Err(Reject::WorkAccounting);
    }
    let embedding = gguf.tensor(&mut source, "token_embd.weight")?;
    let output_norm = gguf.tensor(&mut source, "output_norm.weight")?;

    let mut state = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut norm = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut query = vec![0.0; QWEN3_Q_LENGTH];
    #[cfg(casulo_native_model_resident)]
    let context_positions = 2usize;
    #[cfg(not(casulo_native_model_resident))]
    let context_positions = 1usize;
    let layer_cache_values = context_positions * QWEN3_KV_LENGTH;
    let mut key_cache = vec![0.0; EXPECTED_BLOCKS as usize * layer_cache_values];
    let mut value_cache = vec![0.0; EXPECTED_BLOCKS as usize * layer_cache_values];
    let mut attention_context = vec![0.0; QWEN3_Q_LENGTH];
    let mut projected = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut residual = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut gate = vec![0.0; QWEN3_FFN_LENGTH];
    let mut up = vec![0.0; QWEN3_FFN_LENGTH];
    let mut activated = vec![0.0; QWEN3_FFN_LENGTH];
    let mut down = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut attention_weights = vec![0.0; QWEN3_Q_HEADS * context_positions];
    let mut attn_norm_weight = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut query_norm_weight = vec![0.0; 128];
    let mut key_norm_weight = vec![0.0; 128];
    let mut ffn_norm_weight = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut outputs = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut quantized_input = vec![0.0; QWEN3_FFN_LENGTH];
    let vocabulary = usize::try_from(embedding.dimensions[1]).map_err(|_| Reject::Arena)?;
    let mut logits = vec![0.0; vocabulary];

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
        + quantized_input.len()
        + logits.len();
    let arena_bytes = u32::try_from(arena_values.checked_mul(4).ok_or(Reject::Arena)?)
        .map_err(|_| Reject::Arena)?;
    if arena_bytes > MAX_ARENA_BYTES {
        return Err(Reject::Arena);
    }

    read_q6_k_embedding_row(&mut source, embedding, INPUT_TOKEN_ID, &mut state)?;
    let mut watchdog = DecoderBlockWatchdog::new(EXPECTED_BLOCKS)?;
    let mut cancelled = DecoderBlockWatchdog::new(EXPECTED_BLOCKS)?;
    cancelled.cancel();
    let cancellation_rejected_before_work =
        cancelled.begin_block(0) == Err(WatchdogError::Cancelled);
    if !cancellation_rejected_before_work {
        return Err(Reject::CancellationControl);
    }

    let mut hidden_digest = Sha256::new();
    let mut work = BlockWorkReceipt::default();
    let mut attention_scores = 0u32;
    for block_index in 0..EXPECTED_BLOCKS {
        let block_started = unsafe { core::arch::x86_64::_rdtsc() };
        watchdog.begin_block(block_index)?;
        let layer_start = block_index as usize * layer_cache_values;
        let layer_end = layer_start + layer_cache_values;
        let tensors = gguf.block_tensors(&mut source, block_index)?;
        let mut workspace = QwenBlock0Workspace {
            state: &mut state,
            norm: &mut norm,
            query: &mut query,
            key_cache: &mut key_cache[layer_start..layer_end],
            value_cache: &mut value_cache[layer_start..layer_end],
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
        let block = execute_qwen3_block_np7(
            &mut source,
            &gguf,
            block_index,
            tensors,
            INPUT_TOKEN_ID,
            0,
            &mut workspace,
        )?;
        add_work(&mut work, block.work)?;
        attention_scores = attention_scores
            .checked_add(block.attention_scores)
            .ok_or(Reject::WorkAccounting)?;
        for value in state.iter() {
            hidden_digest.update(value.to_le_bytes());
        }
        watchdog.complete_block(block_index)?;
        let _ = writeln!(
            serial,
            "CASULO_NATIVE_DECODER_BLOCK_{block_index:02}_CYCLES={}",
            unsafe { core::arch::x86_64::_rdtsc() }.wrapping_sub(block_started)
        );
    }
    watchdog.finish()?;
    let hidden_chain_sha256: [u8; 32] = hidden_digest.finalize().into();
    if hidden_chain_sha256 != EXPECTED_HIDDEN_CHAIN_SHA256 {
        return Err(Reject::HiddenHash);
    }

    read_f32_vector(&mut source, output_norm, &mut attn_norm_weight)?;
    rms_norm(&state, &attn_norm_weight, config.rms_epsilon, &mut norm)?;
    let logits_started = unsafe { core::arch::x86_64::_rdtsc() };
    let logits_work = casulo_native_model::quantized_matvec_q8_k_packed(
        &mut source,
        embedding,
        &norm,
        &mut logits,
    )?;
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_DECODER_LOGITS_CYCLES={}",
        unsafe { core::arch::x86_64::_rdtsc() }.wrapping_sub(logits_started)
    );
    add_work(
        &mut work,
        BlockWorkReceipt {
            matvec_calls: 1,
            quantized_blocks: logits_work.quantized_blocks,
            weight_bytes_read: logits_work.weight_bytes_read,
            multiply_accumulates: logits_work.multiply_accumulates,
        },
    )?;
    let mut greedy = 0usize;
    for index in 1..logits.len() {
        if logits[index].total_cmp(&logits[greedy]).is_gt() {
            greedy = index;
        }
    }
    let mut logits_digest = Sha256::new();
    for value in logits.iter() {
        logits_digest.update(value.to_le_bytes());
    }
    let logits_sha256: [u8; 32] = logits_digest.finalize().into();
    if logits_sha256 != EXPECTED_LOGITS_SHA256 {
        return Err(Reject::LogitsHash);
    }
    if greedy as u32 != EXPECTED_GREEDY_TOKEN_ID {
        return Err(Reject::Candidate);
    }
    let tokenizer = gguf.tokenizer(&mut source)?;
    let mut greedy_candidate_text = [0u8; MAX_CANDIDATE_TEXT_BYTES];
    let candidate_len =
        tokenizer.token_text(&mut source, greedy as u32, &mut greedy_candidate_text)?;
    if candidate_len != 3 || &greedy_candidate_text[..candidate_len] != b"ums" {
        return Err(Reject::Candidate);
    }
    if watchdog.completed_blocks() != EXPECTED_BLOCKS
        || work.matvec_calls != EXPECTED_MATVEC_CALLS
        || work.quantized_blocks != EXPECTED_QUANTIZED_BLOCKS
        || work.weight_bytes_read != EXPECTED_WEIGHT_BYTES_READ
        || work.multiply_accumulates != EXPECTED_MULTIPLY_ACCUMULATES
        || attention_scores != EXPECTED_ATTENTION_SCORES
    {
        return Err(Reject::WorkAccounting);
    }

    let mut sampling_gate = sampling_policy.is_none();
    let mut sampling_tokens_authorized = 0u32;
    let mut sampling_steps_total = 0u64;
    let mut sampling_tcap_hash = [0u8; 32];
    let mut sampling_receipt_chain_tail = [0u8; 32];
    let mut candidate_published = false;
    let mut previous_policy_receipt = String::from(ZERO_RECEIPT_HASH);
    if let Some(policy) = sampling_policy {
        let probe = authorize_and_stream_token(
            policy,
            serial,
            0,
            INPUT_TOKEN_ID,
            &logits_sha256,
            greedy as u32,
            &greedy_candidate_text[..candidate_len],
            ZERO_RECEIPT_HASH,
        )?;
        sampling_tcap_hash = parse_hex32(&probe.tcap_hash)?;
        sampling_receipt_chain_tail = parse_hex32(&probe.receipt_hash)?;
        previous_policy_receipt = probe.receipt_hash;
        sampling_tokens_authorized = 1;
        sampling_steps_total = probe.steps;
        candidate_published = true;
        sampling_gate = true;
    }

    #[cfg(casulo_native_model_resident)]
    let cancelled_after_token_boundary =
        candidate_published && cancellation_requested_at_boundary(serial);
    #[cfg(not(casulo_native_model_resident))]
    let cancelled_after_token_boundary = false;

    let mut incremental_tokens_completed = 1u32;
    let mut second_candidate_token_id = 0u32;
    let mut second_hidden_chain_sha256 = [0u8; 32];
    let mut second_logits_sha256 = [0u8; 32];
    let mut second_candidate_text = [0u8; MAX_CANDIDATE_TEXT_BYTES];
    let mut second_candidate_text_len = 0u8;

    let mut second_candidate_published = false;
    #[cfg(casulo_native_model_resident)]
    if !cancelled_after_token_boundary {
        read_q6_k_embedding_row(&mut source, embedding, EXPECTED_GREEDY_TOKEN_ID, &mut state)?;
        let mut second_watchdog = DecoderBlockWatchdog::new(EXPECTED_BLOCKS)?;
        let mut second_hidden_digest = Sha256::new();
        let mut second_work = BlockWorkReceipt::default();
        let mut second_attention_scores = 0u32;
        for block_index in 0..EXPECTED_BLOCKS {
            let block_started = unsafe { core::arch::x86_64::_rdtsc() };
            second_watchdog.begin_block(block_index)?;
            let layer_start = block_index as usize * layer_cache_values;
            let layer_end = layer_start + layer_cache_values;
            let tensors = gguf.block_tensors(&mut source, block_index)?;
            let mut workspace = QwenBlock0Workspace {
                state: &mut state,
                norm: &mut norm,
                query: &mut query,
                key_cache: &mut key_cache[layer_start..layer_end],
                value_cache: &mut value_cache[layer_start..layer_end],
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
            let block = execute_qwen3_block_np7(
                &mut source,
                &gguf,
                block_index,
                tensors,
                EXPECTED_GREEDY_TOKEN_ID,
                1,
                &mut workspace,
            )?;
            add_work(&mut second_work, block.work)?;
            second_attention_scores = second_attention_scores
                .checked_add(block.attention_scores)
                .ok_or(Reject::WorkAccounting)?;
            for value in state.iter() {
                second_hidden_digest.update(value.to_le_bytes());
            }
            second_watchdog.complete_block(block_index)?;
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_INCREMENTAL_TOKEN_1_BLOCK_{block_index:02}_CYCLES={}",
                unsafe { core::arch::x86_64::_rdtsc() }.wrapping_sub(block_started)
            );
        }
        second_watchdog.finish()?;
        second_hidden_chain_sha256 = second_hidden_digest.finalize().into();
        if second_hidden_chain_sha256 != EXPECTED_SECOND_HIDDEN_CHAIN_SHA256 {
            return Err(Reject::HiddenHash);
        }
        read_f32_vector(&mut source, output_norm, &mut attn_norm_weight)?;
        rms_norm(&state, &attn_norm_weight, config.rms_epsilon, &mut norm)?;
        let second_logits_work = casulo_native_model::quantized_matvec_q8_k_packed(
            &mut source,
            embedding,
            &norm,
            &mut logits,
        )?;
        add_work(
            &mut second_work,
            BlockWorkReceipt {
                matvec_calls: 1,
                quantized_blocks: second_logits_work.quantized_blocks,
                weight_bytes_read: second_logits_work.weight_bytes_read,
                multiply_accumulates: second_logits_work.multiply_accumulates,
            },
        )?;
        let mut second_greedy = 0usize;
        for index in 1..logits.len() {
            if logits[index].total_cmp(&logits[second_greedy]).is_gt() {
                second_greedy = index;
            }
        }
        let mut second_logits_digest = Sha256::new();
        for value in logits.iter() {
            second_logits_digest.update(value.to_le_bytes());
        }
        second_logits_sha256 = second_logits_digest.finalize().into();
        if second_logits_sha256 != EXPECTED_SECOND_LOGITS_SHA256
            || second_greedy as u32 != EXPECTED_SECOND_GREEDY_TOKEN_ID
            || second_watchdog.completed_blocks() != EXPECTED_BLOCKS
            || second_work.matvec_calls != EXPECTED_MATVEC_CALLS
            || second_work.quantized_blocks != EXPECTED_QUANTIZED_BLOCKS
            || second_work.weight_bytes_read != EXPECTED_WEIGHT_BYTES_READ
            || second_work.multiply_accumulates != EXPECTED_MULTIPLY_ACCUMULATES
            || second_attention_scores != EXPECTED_BLOCKS * QWEN3_Q_HEADS as u32 * 2
        {
            return Err(Reject::WorkAccounting);
        }
        let second_len = tokenizer.token_text(
            &mut source,
            second_greedy as u32,
            &mut second_candidate_text,
        )?;
        if second_len != 4 || &second_candidate_text[..second_len] != [0xc4, 0xa0, b'i', b's'] {
            return Err(Reject::Candidate);
        }
        incremental_tokens_completed = 2;
        second_candidate_token_id = second_greedy as u32;
        second_candidate_text_len = u8::try_from(second_len).map_err(|_| Reject::Candidate)?;
        if let Some(policy) = sampling_policy {
            let probe = authorize_and_stream_token(
                policy,
                serial,
                1,
                EXPECTED_GREEDY_TOKEN_ID,
                &second_logits_sha256,
                second_greedy as u32,
                &second_candidate_text[..second_len],
                &previous_policy_receipt,
            )?;
            if parse_hex32(&probe.tcap_hash)? != sampling_tcap_hash {
                return Err(Reject::SamplingPolicy);
            }
            sampling_receipt_chain_tail = parse_hex32(&probe.receipt_hash)?;
            sampling_tokens_authorized = 2;
            sampling_steps_total = sampling_steps_total
                .checked_add(probe.steps)
                .ok_or(Reject::SamplingPolicy)?;
            second_candidate_published = true;
            sampling_gate = true;
        }
    }

    Ok(Receipt {
        input_token_id: INPUT_TOKEN_ID,
        blocks_completed: watchdog.completed_blocks(),
        work,
        attention_scores,
        hidden_chain_sha256,
        logits_sha256,
        greedy_candidate_token_id: greedy as u32,
        greedy_candidate_logit_bits: logits[greedy].to_bits(),
        greedy_candidate_text,
        greedy_candidate_text_len: u8::try_from(candidate_len).map_err(|_| Reject::Candidate)?,
        arena_bytes,
        cancellation_rejected_before_work,
        candidate_published,
        sampling_gate,
        sampling_tokens_authorized,
        sampling_steps_total,
        sampling_tcap_hash,
        sampling_receipt_chain_tail,
        cancelled_after_token_boundary,
        incremental_tokens_completed,
        second_candidate_token_id,
        second_hidden_chain_sha256,
        second_logits_sha256,
        second_candidate_text,
        second_candidate_text_len,
        kv_values: u32::try_from(
            EXPECTED_BLOCKS as usize * context_positions * QWEN3_KV_LENGTH * 2,
        )
        .map_err(|_| Reject::Arena)?,
        second_candidate_published,
        stats: source.stats(),
    })
}
