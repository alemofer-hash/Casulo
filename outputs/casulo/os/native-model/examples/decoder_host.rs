use std::env;
use std::fs::File;
use std::io;
use std::path::PathBuf;
use std::time::Instant;

use casulo_native_model::{
    BlockWorkReceipt, Error, NP7_MAX_CONTEXT_TOKENS, PagedQwenGguf, QWEN3_EMBEDDING_LENGTH,
    QWEN3_FFN_LENGTH, QWEN3_KV_LENGTH, QWEN3_Q_HEADS, QWEN3_Q_LENGTH, QwenBlock0Workspace, ReadAt,
    StageSummary, execute_qwen3_block_np7, quantized_matvec, read_f32_vector,
    read_q6_k_embedding_row, rms_norm,
};
use sha2::{Digest, Sha256};

#[cfg(windows)]
use std::os::windows::fs::FileExt;

const CACHE_BYTES: usize = 8 * 1024 * 1024;
const INPUT_TOKEN_ID: u32 = 49_242;

pub(crate) struct FileSource {
    file: File,
    size: u64,
    cache: Vec<u8>,
    cache_offset: u64,
    cache_length: usize,
    reads: u64,
    loaded: u64,
}

impl FileSource {
    pub(crate) fn open(path: &PathBuf) -> io::Result<Self> {
        let file = File::open(path)?;
        let size = file.metadata()?.len();
        Ok(Self {
            file,
            size,
            cache: vec![0; CACHE_BYTES],
            cache_offset: u64::MAX,
            cache_length: 0,
            reads: 0,
            loaded: 0,
        })
    }

    #[cfg(windows)]
    fn fill(&mut self, offset: u64) -> Result<(), Error> {
        let page = offset / CACHE_BYTES as u64 * CACHE_BYTES as u64;
        let length = usize::try_from((self.size - page).min(CACHE_BYTES as u64))
            .map_err(|_| Error::Bounds)?;
        let mut completed = 0usize;
        while completed < length {
            let count = self
                .file
                .seek_read(&mut self.cache[completed..length], page + completed as u64)
                .map_err(|_| Error::Source)?;
            if count == 0 {
                return Err(Error::Truncated);
            }
            completed += count;
        }
        self.cache_offset = page;
        self.cache_length = length;
        self.reads += 1;
        self.loaded += length as u64;
        Ok(())
    }
}

impl ReadAt for FileSource {
    fn len(&self) -> u64 {
        self.size
    }

    fn read_exact_at(&mut self, offset: u64, output: &mut [u8]) -> Result<(), Error> {
        let end = offset
            .checked_add(output.len() as u64)
            .ok_or(Error::Bounds)?;
        if end > self.size {
            return Err(Error::Truncated);
        }
        let mut input_offset = offset;
        let mut output_offset = 0usize;
        while output_offset < output.len() {
            let cache_end = self.cache_offset.saturating_add(self.cache_length as u64);
            if input_offset < self.cache_offset || input_offset >= cache_end {
                self.fill(input_offset)?;
            }
            let within =
                usize::try_from(input_offset - self.cache_offset).map_err(|_| Error::Bounds)?;
            let copied = (self.cache_length - within).min(output.len() - output_offset);
            output[output_offset..output_offset + copied]
                .copy_from_slice(&self.cache[within..within + copied]);
            input_offset += copied as u64;
            output_offset += copied;
        }
        Ok(())
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("DECODER_HOST_ERROR={error:?}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Error> {
    let model = env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or(Error::Missing)?;
    let started = Instant::now();
    let mut source = FileSource::open(&model).map_err(|_| Error::Source)?;
    let gguf = PagedQwenGguf::parse(&mut source)?;
    let config = gguf.config();
    let embedding = gguf.tensor(&mut source, "token_embd.weight")?;
    let output_norm = gguf.tensor(&mut source, "output_norm.weight")?;

    let mut state = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut norm = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut query = vec![0.0; QWEN3_Q_LENGTH];
    let mut key_cache = vec![0.0; NP7_MAX_CONTEXT_TOKENS * QWEN3_KV_LENGTH];
    let mut value_cache = vec![0.0; NP7_MAX_CONTEXT_TOKENS * QWEN3_KV_LENGTH];
    let mut attention_context = vec![0.0; QWEN3_Q_LENGTH];
    let mut projected = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut residual = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut gate = vec![0.0; QWEN3_FFN_LENGTH];
    let mut up = vec![0.0; QWEN3_FFN_LENGTH];
    let mut activated = vec![0.0; QWEN3_FFN_LENGTH];
    let mut down = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut attention_weights = vec![0.0; QWEN3_Q_HEADS * NP7_MAX_CONTEXT_TOKENS];
    let mut attn_norm_weight = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut query_norm_weight = vec![0.0; 128];
    let mut key_norm_weight = vec![0.0; 128];
    let mut ffn_norm_weight = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut outputs = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut quantized_input = vec![0.0; QWEN3_FFN_LENGTH];

    read_q6_k_embedding_row(&mut source, embedding, INPUT_TOKEN_ID, &mut state)?;
    let mut total = BlockWorkReceipt::default();
    let mut hidden_digest = Sha256::new();
    for block_index in 0..config.block_count {
        key_cache.fill(0.0);
        value_cache.fill(0.0);
        let tensors = gguf.block_tensors(&mut source, block_index)?;
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
        let receipt = execute_qwen3_block_np7(
            &mut source,
            &gguf,
            block_index,
            tensors,
            INPUT_TOKEN_ID,
            0,
            &mut workspace,
        )?;
        total.matvec_calls += receipt.work.matvec_calls;
        total.quantized_blocks += receipt.work.quantized_blocks;
        total.weight_bytes_read += receipt.work.weight_bytes_read;
        total.multiply_accumulates += receipt.work.multiply_accumulates;
        for value in state.iter() {
            hidden_digest.update(value.to_le_bytes());
        }
        println!(
            "BLOCK|{}|{:.17}|{:.17}|{:.9}|{:.9}",
            block_index,
            receipt.stages.block_output.sum_f64,
            receipt.stages.block_output.square_sum_f64,
            receipt.stages.block_output.minimum,
            receipt.stages.block_output.maximum
        );
    }

    read_f32_vector(&mut source, output_norm, &mut attn_norm_weight)?;
    rms_norm(&state, &attn_norm_weight, config.rms_epsilon, &mut norm)?;
    let mut logits = vec![0.0f32; embedding.dimensions[1] as usize];
    let logits_work = casulo_native_model::quantized_matvec_q8_k_packed(
        &mut source,
        embedding,
        &norm,
        &mut logits,
    )?;
    let mut best_id = 0usize;
    for index in 1..logits.len() {
        if logits[index].total_cmp(&logits[best_id]).is_gt() {
            best_id = index;
        }
    }
    let tokenizer = gguf.tokenizer(&mut source)?;
    let mut token_text = [0u8; 256];
    let token_text_len = tokenizer.token_text(&mut source, best_id as u32, &mut token_text)?;
    let mut logits_digest = Sha256::new();
    for value in logits.iter() {
        logits_digest.update(value.to_le_bytes());
    }
    if let Some(path) = env::args_os().nth(2).map(PathBuf::from) {
        let mut bytes = Vec::with_capacity(logits.len() * 4);
        for value in logits.iter() {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        std::fs::write(path, bytes).map_err(|_| Error::Source)?;
    }
    println!("BLOCKS_COMPLETED={}", config.block_count);
    println!("MATVEC_CALLS={}", total.matvec_calls + 1);
    println!(
        "QUANTIZED_BLOCKS={}",
        total.quantized_blocks + logits_work.quantized_blocks
    );
    println!(
        "MULTIPLY_ACCUMULATES={}",
        total.multiply_accumulates + logits_work.multiply_accumulates
    );
    println!(
        "WEIGHT_BYTES_READ={}",
        total.weight_bytes_read + logits_work.weight_bytes_read
    );
    println!("HIDDEN_CHAIN_SHA256={:x}", hidden_digest.finalize());
    println!("LOGITS_SHA256={:x}", logits_digest.finalize());
    let normalized_summary = StageSummary::from_values(&norm)?;
    let logits_summary = StageSummary::from_values(&logits)?;
    println!(
        "FINAL_NORM|{}|{:.17}|{:.17}|{:.9}|{:.9}",
        normalized_summary.values,
        normalized_summary.sum_f64,
        normalized_summary.square_sum_f64,
        normalized_summary.minimum,
        normalized_summary.maximum
    );
    println!(
        "LOGITS|{}|{:.17}|{:.17}|{:.9}|{:.9}",
        logits_summary.values,
        logits_summary.sum_f64,
        logits_summary.square_sum_f64,
        logits_summary.minimum,
        logits_summary.maximum
    );
    println!("GREEDY_TOKEN_ID={best_id}");
    println!("GREEDY_TOKEN_LOGIT={:.9}", logits[best_id]);
    println!(
        "GREEDY_TOKEN_TEXT_HEX={}",
        hex(&token_text[..token_text_len])
    );
    println!("CACHE_LOADS={}", source.reads);
    println!("CACHE_BYTES_LOADED={}", source.loaded);
    println!("ELAPSED_MS={:.3}", started.elapsed().as_secs_f64() * 1000.0);
    Ok(())
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}
