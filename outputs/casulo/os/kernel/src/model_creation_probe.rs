//! NP10 bounded boot-to-creation vertical slice.
//!
//! The complete adopted Qwen3 model decodes a frozen natural-language request
//! from weights inside Casulo Native. Every candidate token is judged by the
//! compiled T policy before publication. The resulting CreationSpec is parsed
//! structurally, lowered to a bounded T source, matched to a content-addressed
//! compilation cache, executed, simulated and accepted by a second T policy.

extern crate alloc;

use alloc::{format, string::String, vec, vec::Vec};
use casulo_native_model::{
    BlockWorkReceipt, DecoderBlockWatchdog, Error as ModelError, PagedQwenGguf,
    QWEN3_EMBEDDING_LENGTH, QWEN3_FFN_LENGTH, QWEN3_KV_LENGTH, QWEN3_Q_HEADS, QWEN3_Q_LENGTH,
    QwenBlock0Tensors, QwenBlock0Workspace, ReadAt, WatchdogError, execute_qwen3_block_np7,
    read_f32_vector, read_q6_k_embedding_row, rms_norm,
};
use core::{fmt::Write, str};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use crate::fw_cfg::{self, ReadStats};
use crate::memory::MemorySummary;
use crate::model_paged_probe::EXPECTED_MODEL_BYTES;
use crate::serial::Serial;
use crate::tcap_v2;

const EXPECTED_BLOCKS: u32 = 36;
const EXPECTED_MATVEC_CALLS_PER_POSITION: u32 = 253;
const EXPECTED_QUANTIZED_BLOCKS_PER_POSITION: u64 = 15_712_000;
const EXPECTED_WEIGHT_BYTES_PER_POSITION: u64 = 2_490_539_520;
const EXPECTED_MACS_PER_POSITION: u64 = 4_022_272_000;
const CONTEXT_CAPACITY: usize = 96;
const MAX_PROMPT_TOKENS: usize = 50;
const MAX_OUTPUT_TOKENS: usize = 40;
const MAX_CREATION_TEXT_BYTES: usize = 256;
const ZERO_HASH: &str = "0000000000000000000000000000000000000000000000000000000000000000";
const MODEL_SHA256: &str = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5";
pub const MODEL_SHA256_BYTES: [u8; 32] = [
    0x74, 0x85, 0xfe, 0x6f, 0x11, 0xaf, 0x29, 0x43, 0x3b, 0xc5, 0x1c, 0xab, 0x58, 0x00, 0x95, 0x21,
    0xf2, 0x05, 0x84, 0x0f, 0x5b, 0x4a, 0xe3, 0xa3, 0x2f, 0xa7, 0xf9, 0x2e, 0x85, 0x34, 0xfd, 0xf5,
];
const TOKEN_POLICY_ID: &str = "greedy-creation-v1";
const GENERATED_T_SOURCE: &str = concat!(
    "language T/2.0\n",
    "module owner.generated.some_dois_numeros\n",
    "budget steps 64\n",
    "budget deadline_ms 1000\n",
    "schema version 1\n",
    "\n",
    "record SomeDoisNumerosInput\n",
    "  member left: Int\n",
    "  member right: Int\n",
    "  member cancelled: Bool\n",
    "\n",
    "fn execute(input: SomeDoisNumerosInput) -> Result<Int,Text>\n",
    "  cancel if input.cancelled\n",
    "  return ok add(input.left, input.right)\n",
);

// Input is checked at runtime against the frozen llama.cpp oracle in the
// content-addressed prompt entry. It is never used to choose the token.
#[derive(Clone, Copy)]
struct PromptContract {
    ids: [u32; MAX_PROMPT_TOKENS],
    expected: [u32; MAX_OUTPUT_TOKENS],
    expected_len: usize,
    max_output: usize,
    prompt_sha256: [u8; 32],
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum Reject {
    Transport(fw_cfg::Reject),
    Model(ModelError),
    Watchdog(WatchdogError),
    Prompt,
    WorkAccounting,
    TokenPolicy,
    OracleMismatch,
    CreationSpec,
    SourceIdentity,
    Artifact,
    Acceptance,
    Arena,
    Projection,
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
pub enum ModelTransport {
    QemuFwCfgResident,
    UefiRamdiskValidated,
}

impl ModelTransport {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::QemuFwCfgResident => "qemu-fw-cfg-resident/0.1",
            Self::UefiRamdiskValidated => "uefi-ramdisk-content-addressed/1.0",
        }
    }
}

struct RamdiskModelFile<'a> {
    bytes: &'a [u8],
    stats: ReadStats,
}

impl<'a> RamdiskModelFile<'a> {
    fn open(bytes: &'a [u8], expected_size: u64) -> Result<Self, Reject> {
        if u64::try_from(bytes.len()).map_err(|_| Reject::Model(ModelError::Bounds))?
            != expected_size
        {
            return Err(Reject::Model(ModelError::Mismatch));
        }
        Ok(Self {
            bytes,
            stats: ReadStats {
                dma_operations: 0,
                cache_pages_loaded: 1,
                bytes_copied_to_consumer: 0,
                bytes_loaded_from_source: expected_size,
                largest_requested_end: 0,
            },
        })
    }
}

impl ReadAt for RamdiskModelFile<'_> {
    fn len(&self) -> u64 {
        self.bytes.len() as u64
    }

    fn read_exact_at(&mut self, offset: u64, output: &mut [u8]) -> Result<(), ModelError> {
        let start = usize::try_from(offset).map_err(|_| ModelError::Bounds)?;
        let end = start.checked_add(output.len()).ok_or(ModelError::Bounds)?;
        let source = self.bytes.get(start..end).ok_or(ModelError::Truncated)?;
        output.copy_from_slice(source);
        self.stats.bytes_copied_to_consumer = self
            .stats
            .bytes_copied_to_consumer
            .checked_add(output.len() as u64)
            .ok_or(ModelError::Bounds)?;
        self.stats.largest_requested_end = self.stats.largest_requested_end.max(end as u64);
        Ok(())
    }
}

enum CreationModelFile<'a> {
    Qemu(fw_cfg::ModelFile),
    Ramdisk(RamdiskModelFile<'a>),
}

impl<'a> CreationModelFile<'a> {
    fn open(
        memory: &mut MemorySummary,
        ramdisk_model: Option<&'a [u8]>,
    ) -> Result<(Self, ModelTransport), Reject> {
        if let Some(bytes) = ramdisk_model {
            return Ok((
                Self::Ramdisk(RamdiskModelFile::open(bytes, EXPECTED_MODEL_BYTES)?),
                ModelTransport::UefiRamdiskValidated,
            ));
        }
        Ok((
            Self::Qemu(fw_cfg::ModelFile::open_resident(
                memory,
                EXPECTED_MODEL_BYTES,
            )?),
            ModelTransport::QemuFwCfgResident,
        ))
    }

    fn stats(&self) -> ReadStats {
        match self {
            Self::Qemu(source) => source.stats(),
            Self::Ramdisk(source) => source.stats,
        }
    }
}

impl ReadAt for CreationModelFile<'_> {
    fn len(&self) -> u64 {
        match self {
            Self::Qemu(source) => source.len(),
            Self::Ramdisk(source) => source.len(),
        }
    }

    fn read_exact_at(&mut self, offset: u64, output: &mut [u8]) -> Result<(), ModelError> {
        match self {
            Self::Qemu(source) => source.read_exact_at(offset, output),
            Self::Ramdisk(source) => source.read_exact_at(offset, output),
        }
    }
}

#[derive(Clone, Debug)]
pub struct Receipt {
    pub prompt_tokens: u32,
    pub output_tokens: u32,
    pub output_ids: [u32; MAX_OUTPUT_TOKENS],
    pub output_text: [u8; MAX_CREATION_TEXT_BYTES],
    pub output_text_len: u16,
    pub token_policy_tcap_hash: [u8; 32],
    pub token_receipt_chain_tail: [u8; 32],
    pub token_policy_steps: u64,
    pub model_positions_completed: u32,
    pub blocks_completed: u32,
    pub work: BlockWorkReceipt,
    pub arena_bytes: u32,
    pub cancelled: bool,
    pub late_output_published: bool,
    pub creation_spec_valid: bool,
    pub generated_t_source_sha256: [u8; 32],
    pub compiled_t_source_sha256: [u8; 32],
    pub artifact_tcap_hash: [u8; 32],
    pub artifact_result: i64,
    pub simulation_pass: bool,
    pub materialization_sha256: [u8; 32],
    pub acceptance_tcap_hash: [u8; 32],
    pub acceptance_receipt_hash: [u8; 32],
    pub acceptance_pass: bool,
    pub model_transport: ModelTransport,
    pub stats: ReadStats,
}

impl Receipt {
    pub fn gate(&self) -> bool {
        if self.cancelled {
            self.output_tokens > 0
                && !self.late_output_published
                && !self.acceptance_pass
                && self.artifact_result == 0
        } else {
            self.output_tokens == 34
                // Token zero is produced by the final prompt position. Every
                // later token consumes the preceding generated token, while
                // the terminal token is published but never fed forward.
                && self.model_positions_completed
                    == self.prompt_tokens + self.output_tokens.saturating_sub(1)
                && self.blocks_completed == self.model_positions_completed * EXPECTED_BLOCKS
                && self.creation_spec_valid
                && self.generated_t_source_sha256 == self.compiled_t_source_sha256
                && self.artifact_result == 18
                && self.simulation_pass
                && self.acceptance_pass
                && !self.late_output_published
        }
    }
}

struct CreationSpec<'a> {
    name: &'a str,
    function: &'a str,
    input: &'a str,
    output: &'a str,
}

fn sha(value: &[u8]) -> [u8; 32] {
    Sha256::digest(value).into()
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
        return Err(Reject::TokenPolicy);
    }
    let mut output = [0u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = (pair[0] as char).to_digit(16).ok_or(Reject::TokenPolicy)? as u8;
        let low = (pair[1] as char).to_digit(16).ok_or(Reject::TokenPolicy)? as u8;
        output[index] = high << 4 | low;
    }
    Ok(output)
}

fn parse_prompt(raw: &[u8]) -> Result<PromptContract, Reject> {
    let value: Value = serde_json::from_slice(raw).map_err(|_| Reject::Prompt)?;
    if value.get("schema").and_then(Value::as_str) != Some("casulo.native-creation-prompt/1.0")
        || value.get("model_sha256").and_then(Value::as_str) != Some(MODEL_SHA256)
        || value.get("sampling").and_then(Value::as_str) != Some("greedy")
        || value.get("sampling_policy_id").and_then(Value::as_str) != Some(TOKEN_POLICY_ID)
    {
        return Err(Reject::Prompt);
    }
    let prompt = value
        .get("prompt_token_ids")
        .and_then(Value::as_array)
        .ok_or(Reject::Prompt)?;
    let expected = value
        .get("frozen_llama_cpp_oracle")
        .and_then(|item| item.get("output_token_ids"))
        .and_then(Value::as_array)
        .ok_or(Reject::Prompt)?;
    let max_output = value
        .get("max_output_tokens")
        .and_then(Value::as_u64)
        .and_then(|item| usize::try_from(item).ok())
        .ok_or(Reject::Prompt)?;
    if prompt.len() != MAX_PROMPT_TOKENS
        || expected.is_empty()
        || expected.len() > MAX_OUTPUT_TOKENS
        || max_output != MAX_OUTPUT_TOKENS
    {
        return Err(Reject::Prompt);
    }
    let mut ids = [0u32; MAX_PROMPT_TOKENS];
    for (slot, item) in ids.iter_mut().zip(prompt) {
        *slot = item
            .as_u64()
            .and_then(|value| u32::try_from(value).ok())
            .ok_or(Reject::Prompt)?;
    }
    let mut expected_ids = [0u32; MAX_OUTPUT_TOKENS];
    for (slot, item) in expected_ids.iter_mut().zip(expected) {
        *slot = item
            .as_u64()
            .and_then(|value| u32::try_from(value).ok())
            .ok_or(Reject::Prompt)?;
    }
    Ok(PromptContract {
        ids,
        expected: expected_ids,
        expected_len: expected.len(),
        max_output,
        prompt_sha256: sha(raw),
    })
}

fn parse_creation_spec(text: &[u8]) -> Result<CreationSpec<'_>, Reject> {
    let text = str::from_utf8(text).map_err(|_| Reject::CreationSpec)?;
    let mut parts = text.split(';');
    let name = parts
        .next()
        .and_then(|value| value.strip_prefix("NOME="))
        .filter(|value| !value.is_empty())
        .ok_or(Reject::CreationSpec)?;
    let function = parts
        .next()
        .and_then(|value| value.strip_prefix("FUNCAO="))
        .filter(|value| !value.is_empty())
        .ok_or(Reject::CreationSpec)?;
    let input = parts
        .next()
        .and_then(|value| value.strip_prefix("ENTRADA="))
        .filter(|value| !value.is_empty())
        .ok_or(Reject::CreationSpec)?;
    let output = parts
        .next()
        .and_then(|value| value.strip_prefix("SAIDA="))
        .filter(|value| !value.is_empty())
        .ok_or(Reject::CreationSpec)?;
    if parts.next().is_some() {
        return Err(Reject::CreationSpec);
    }
    Ok(CreationSpec {
        name,
        function,
        input,
        output,
    })
}

fn compile_bounded_t(spec: &CreationSpec<'_>) -> Result<String, Reject> {
    if spec.name != "SomeDoisNumeros"
        || spec.function != "SomeDoisNumeros"
        || spec.input != "numero1,numero2"
        || spec.output != "resultado."
    {
        return Err(Reject::CreationSpec);
    }
    // This is deliberately a bounded compiler for the first vertical slice,
    // not a claim of arbitrary T compilation in the kernel.
    Ok(format!("{GENERATED_T_SOURCE}"))
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

fn cancellation_requested(serial: &mut Serial) -> bool {
    const WINDOW_CYCLES: u64 = 500_000_000;
    let started = unsafe { core::arch::x86_64::_rdtsc() };
    let _ = writeln!(serial, "CASULO_NATIVE_CREATION_CANCEL_WINDOW=OPEN");
    while unsafe { core::arch::x86_64::_rdtsc() }.wrapping_sub(started) < WINDOW_CYCLES {
        if let Some(byte) = serial.try_read_byte() {
            if matches!(byte, 0x03 | 0x1b | b'c' | b'C') {
                let _ = writeln!(serial, "CASULO_NATIVE_CREATION_CANCEL=ACCEPTED");
                return true;
            }
        }
        core::hint::spin_loop();
    }
    let _ = writeln!(serial, "CASULO_NATIVE_CREATION_CANCEL_WINDOW=CLOSED");
    false
}

#[allow(clippy::too_many_arguments)]
pub fn run<F>(
    memory: &mut MemorySummary,
    serial: &mut Serial,
    ramdisk_model: Option<&[u8]>,
    token_policy: &[u8],
    prompt_raw: &[u8],
    artifact_policy: &[u8],
    acceptance_policy: &[u8],
    mut on_token: F,
) -> Result<Receipt, Reject>
where
    F: FnMut(u32, &[u8], [u8; 32]) -> bool,
{
    let contract = parse_prompt(prompt_raw)?;
    let (mut source, model_transport) = CreationModelFile::open(memory, ramdisk_model)?;
    let gguf = PagedQwenGguf::parse(&mut source)?;
    let config = gguf.config();
    if config.block_count != EXPECTED_BLOCKS {
        return Err(Reject::WorkAccounting);
    }
    let embedding = gguf.tensor(&mut source, "token_embd.weight")?;
    let output_norm = gguf.tensor(&mut source, "output_norm.weight")?;
    let tokenizer = gguf.tokenizer(&mut source)?;
    let mut tensors: Vec<QwenBlock0Tensors> = Vec::with_capacity(EXPECTED_BLOCKS as usize);
    for block in 0..EXPECTED_BLOCKS {
        tensors.push(gguf.block_tensors(&mut source, block)?);
    }

    let mut state = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut norm = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut query = vec![0.0; QWEN3_Q_LENGTH];
    let layer_cache_values = CONTEXT_CAPACITY * QWEN3_KV_LENGTH;
    let mut key_cache = vec![0.0; EXPECTED_BLOCKS as usize * layer_cache_values];
    let mut value_cache = vec![0.0; EXPECTED_BLOCKS as usize * layer_cache_values];
    let mut attention_context = vec![0.0; QWEN3_Q_LENGTH];
    let mut projected = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut residual = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut gate = vec![0.0; QWEN3_FFN_LENGTH];
    let mut up = vec![0.0; QWEN3_FFN_LENGTH];
    let mut activated = vec![0.0; QWEN3_FFN_LENGTH];
    let mut down = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut attention_weights = vec![0.0; QWEN3_Q_HEADS * CONTEXT_CAPACITY];
    let mut attn_norm_weight = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut query_norm_weight = vec![0.0; 128];
    let mut key_norm_weight = vec![0.0; 128];
    let mut ffn_norm_weight = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut outputs = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut quantized_input = vec![0.0; QWEN3_FFN_LENGTH];
    let vocabulary = usize::try_from(embedding.dimensions[1]).map_err(|_| Reject::Arena)?;
    let mut logits = vec![0.0f32; vocabulary];
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
    if arena_bytes > 40 * 1_024 * 1_024 {
        return Err(Reject::Arena);
    }

    let mut output_ids = [0u32; MAX_OUTPUT_TOKENS];
    let mut output_text = [0u8; MAX_CREATION_TEXT_BYTES];
    let mut output_count = 0usize;
    let mut output_text_len = 0usize;
    let mut next_input = 0u32;
    let mut total_work = BlockWorkReceipt::default();
    let mut total_blocks = 0u32;
    let mut token_policy_steps = 0u64;
    let mut token_policy_hash = [0u8; 32];
    let mut receipt_tail = [0u8; 32];
    let mut previous_receipt = String::from(ZERO_HASH);

    let _ = writeln!(
        serial,
        "CASULO_NATIVE_CREATION_PROMPT_TOKENS={MAX_PROMPT_TOKENS}"
    );
    let _ = writeln!(serial, "CASULO_NATIVE_CREATION_PREFILL=BEGIN");
    for position in 0..CONTEXT_CAPACITY {
        let token_id = if position < MAX_PROMPT_TOKENS {
            contract.ids[position]
        } else {
            next_input
        };
        read_q6_k_embedding_row(&mut source, embedding, token_id, &mut state)?;
        let mut watchdog = DecoderBlockWatchdog::new(EXPECTED_BLOCKS)?;
        let mut position_work = BlockWorkReceipt::default();
        for block_index in 0..EXPECTED_BLOCKS {
            watchdog.begin_block(block_index)?;
            let layer_start = block_index as usize * layer_cache_values;
            let layer_end = layer_start + layer_cache_values;
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
            let observed = execute_qwen3_block_np7(
                &mut source,
                &gguf,
                block_index,
                tensors[block_index as usize],
                token_id,
                position,
                &mut workspace,
            )?;
            add_work(&mut position_work, observed.work)?;
            watchdog.complete_block(block_index)?;
        }
        watchdog.finish()?;
        let logits_work = {
            read_f32_vector(&mut source, output_norm, &mut attn_norm_weight)?;
            rms_norm(&state, &attn_norm_weight, config.rms_epsilon, &mut norm)?;
            casulo_native_model::quantized_matvec_q8_k_packed(
                &mut source,
                embedding,
                &norm,
                &mut logits,
            )?
        };
        add_work(
            &mut position_work,
            BlockWorkReceipt {
                matvec_calls: 1,
                quantized_blocks: logits_work.quantized_blocks,
                weight_bytes_read: logits_work.weight_bytes_read,
                multiply_accumulates: logits_work.multiply_accumulates,
            },
        )?;
        if position_work.matvec_calls != EXPECTED_MATVEC_CALLS_PER_POSITION
            || position_work.quantized_blocks != EXPECTED_QUANTIZED_BLOCKS_PER_POSITION
            || position_work.weight_bytes_read != EXPECTED_WEIGHT_BYTES_PER_POSITION
            || position_work.multiply_accumulates != EXPECTED_MACS_PER_POSITION
        {
            return Err(Reject::WorkAccounting);
        }
        add_work(&mut total_work, position_work)?;
        total_blocks = total_blocks
            .checked_add(EXPECTED_BLOCKS)
            .ok_or(Reject::WorkAccounting)?;
        if position + 1 < MAX_PROMPT_TOKENS {
            if (position + 1).is_multiple_of(10) {
                let _ = writeln!(
                    serial,
                    "CASULO_NATIVE_CREATION_PREFILL_POSITIONS={}",
                    position + 1
                );
            }
            continue;
        }
        if position + 1 == MAX_PROMPT_TOKENS {
            let _ = writeln!(serial, "CASULO_NATIVE_CREATION_PREFILL=PASS");
        }

        let greedy = (1..logits.len()).fold(0usize, |best, index| {
            if logits[index].total_cmp(&logits[best]).is_gt() {
                index
            } else {
                best
            }
        });
        let logits_sha256 = {
            let mut digest = Sha256::new();
            for value in &logits {
                digest.update(value.to_le_bytes());
            }
            <[u8; 32]>::from(digest.finalize())
        };
        let mut token_text = [0u8; 64];
        let token_text_len = tokenizer.token_text(&mut source, greedy as u32, &mut token_text)?;
        let payload = json!({
            "decoder_gate": true,
            "token_index": output_count,
            "max_tokens": contract.max_output,
            "input_token_id": token_id,
            "logits_sha256": hex32(&logits_sha256),
            "blocks_completed": EXPECTED_BLOCKS,
            "greedy_candidate_id": greedy,
            "candidate_unpublished": true,
            "model_sha256": MODEL_SHA256,
            "prompt_sha256": hex32(&contract.prompt_sha256),
            "policy_id": TOKEN_POLICY_ID,
            "previous_receipt_hash": previous_receipt,
            "cancelled": false,
        });
        let decision = tcap_v2::execute_with_payload(
            token_policy,
            &payload,
            if output_count == 0 {
                None
            } else {
                Some(&previous_receipt)
            },
        )
        .map_err(|_| Reject::TokenPolicy)?;
        if decision.result.get("kind").and_then(Value::as_str) != Some("ok")
            || decision.result.get("value").and_then(Value::as_str) != Some("PUBLISH_TOKEN")
        {
            return Err(Reject::TokenPolicy);
        }
        let observed_policy_hash = parse_hex32(&decision.tcap_hash)?;
        if output_count == 0 {
            token_policy_hash = observed_policy_hash;
        } else if token_policy_hash != observed_policy_hash {
            return Err(Reject::TokenPolicy);
        }
        receipt_tail = parse_hex32(&decision.receipt_hash)?;
        previous_receipt = decision.receipt_hash;
        token_policy_steps = token_policy_steps
            .checked_add(decision.steps)
            .ok_or(Reject::TokenPolicy)?;
        if output_count >= MAX_OUTPUT_TOKENS
            || output_text_len + token_text_len > MAX_CREATION_TEXT_BYTES
        {
            return Err(Reject::Arena);
        }
        output_ids[output_count] = greedy as u32;
        output_text[output_text_len..output_text_len + token_text_len]
            .copy_from_slice(&token_text[..token_text_len]);
        output_text_len += token_text_len;
        let _ = writeln!(serial, "CASULO_NATIVE_CREATION_TOKEN_{output_count}_BEGIN");
        let _ = writeln!(
            serial,
            "CASULO_NATIVE_CREATION_TOKEN_{output_count}_ID={greedy}"
        );
        let _ = write!(
            serial,
            "CASULO_NATIVE_CREATION_TOKEN_{output_count}_TEXT_HEX="
        );
        for byte in &token_text[..token_text_len] {
            let _ = write!(serial, "{byte:02x}");
        }
        let _ = writeln!(serial);
        let _ = writeln!(
            serial,
            "CASULO_NATIVE_CREATION_TOKEN_{output_count}_T_RECEIPT_HASH={}",
            previous_receipt
        );
        let _ = writeln!(
            serial,
            "CASULO_NATIVE_CREATION_TOKEN_{output_count}_PUBLICATION=PASS"
        );
        let _ = writeln!(serial, "CASULO_NATIVE_CREATION_TOKEN_{output_count}_END");
        if !on_token(
            output_count as u32,
            &token_text[..token_text_len],
            receipt_tail,
        ) {
            return Err(Reject::Projection);
        }
        output_count += 1;
        next_input = greedy as u32;
        if cancellation_requested(serial) {
            return Ok(Receipt {
                prompt_tokens: MAX_PROMPT_TOKENS as u32,
                output_tokens: output_count as u32,
                output_ids,
                output_text,
                output_text_len: output_text_len as u16,
                token_policy_tcap_hash: token_policy_hash,
                token_receipt_chain_tail: receipt_tail,
                token_policy_steps,
                model_positions_completed: (position + 1) as u32,
                blocks_completed: total_blocks,
                work: total_work,
                arena_bytes,
                cancelled: true,
                late_output_published: false,
                creation_spec_valid: false,
                generated_t_source_sha256: [0; 32],
                compiled_t_source_sha256: [0; 32],
                artifact_tcap_hash: [0; 32],
                artifact_result: 0,
                simulation_pass: false,
                materialization_sha256: [0; 32],
                acceptance_tcap_hash: [0; 32],
                acceptance_receipt_hash: [0; 32],
                acceptance_pass: false,
                model_transport,
                stats: source.stats(),
            });
        }
        if greedy as u32 == 13 || output_count == contract.max_output {
            break;
        }
    }

    if output_count != contract.expected_len
        || output_ids[..output_count] != contract.expected[..contract.expected_len]
    {
        return Err(Reject::OracleMismatch);
    }
    let spec = parse_creation_spec(&output_text[..output_text_len])?;
    let generated_source = compile_bounded_t(&spec)?;
    let generated_source_sha256 = sha(generated_source.as_bytes());

    let artifact = tcap_v2::execute_with_payload(
        artifact_policy,
        &json!({"left": 7, "right": 11, "cancelled": false}),
        Some(&previous_receipt),
    )
    .map_err(|_| Reject::Artifact)?;
    let artifact_result = artifact
        .result
        .get("value")
        .and_then(Value::as_i64)
        .ok_or(Reject::Artifact)?;
    let artifact_receipt: Value =
        serde_json::from_str(&artifact.receipt).map_err(|_| Reject::Artifact)?;
    let compiled_source_sha256 = parse_hex32(
        artifact_receipt
            .get("t_source_hash")
            .and_then(Value::as_str)
            .ok_or(Reject::Artifact)?,
    )?;
    if generated_source_sha256 != compiled_source_sha256 {
        return Err(Reject::SourceIdentity);
    }
    let artifact_tcap_hash = parse_hex32(&artifact.tcap_hash)?;
    let simulation_pass = artifact_result == 18;
    let materialization = json!({
        "schema": "casulo.native-materialization/1.0",
        "creation_id": "SomeDoisNumeros",
        "artifact_tcap_hash": artifact.tcap_hash,
        "generated_t_source_sha256": hex32(&generated_source_sha256),
        "simulation": {"left": 7, "right": 11, "result": artifact_result},
        "effects": [],
    });
    let materialization_bytes =
        serde_json::to_vec(&materialization).map_err(|_| Reject::Artifact)?;
    let materialization_sha256 = sha(&materialization_bytes);
    let acceptance = tcap_v2::execute_with_payload(
        acceptance_policy,
        &json!({
            "model_output_valid": true,
            "creation_name": spec.name,
            "function_name": spec.function,
            "input_contract": spec.input,
            "output_contract": spec.output,
            "generated_t_source_sha256": hex32(&generated_source_sha256),
            "compiled_t_source_sha256": hex32(&compiled_source_sha256),
            "artifact_tcap_hash": hex32(&artifact_tcap_hash),
            "simulation_status": if simulation_pass { "PASS" } else { "FAIL" },
            "simulation_left": 7,
            "simulation_right": 11,
            "simulation_result": artifact_result,
            "expected_result": 18,
            "effects_requested": 0,
            "materialization_hash": hex32(&materialization_sha256),
            "cancelled": false,
        }),
        Some(&artifact.receipt_hash),
    )
    .map_err(|_| Reject::Acceptance)?;
    let acceptance_pass = acceptance.result.get("kind").and_then(Value::as_str) == Some("ok")
        && acceptance.result.get("value").and_then(Value::as_str) == Some("ACCEPT_MATERIALIZATION");
    if !acceptance_pass {
        return Err(Reject::Acceptance);
    }
    let acceptance_tcap_hash = parse_hex32(&acceptance.tcap_hash)?;
    let acceptance_receipt_hash = parse_hex32(&acceptance.receipt_hash)?;
    let model_positions_completed = MAX_PROMPT_TOKENS + output_count.saturating_sub(1);
    Ok(Receipt {
        prompt_tokens: MAX_PROMPT_TOKENS as u32,
        output_tokens: output_count as u32,
        output_ids,
        output_text,
        output_text_len: output_text_len as u16,
        token_policy_tcap_hash: token_policy_hash,
        token_receipt_chain_tail: receipt_tail,
        token_policy_steps,
        model_positions_completed: model_positions_completed as u32,
        blocks_completed: total_blocks,
        work: total_work,
        arena_bytes,
        cancelled: false,
        late_output_published: false,
        creation_spec_valid: true,
        generated_t_source_sha256: generated_source_sha256,
        compiled_t_source_sha256: compiled_source_sha256,
        artifact_tcap_hash,
        artifact_result,
        simulation_pass,
        materialization_sha256,
        acceptance_tcap_hash,
        acceptance_receipt_hash,
        acceptance_pass,
        model_transport,
        stats: source.stats(),
    })
}
