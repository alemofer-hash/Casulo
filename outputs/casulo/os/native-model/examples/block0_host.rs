use std::env;
use std::fs::File;
use std::io;
use std::path::PathBuf;

use casulo_native_model::{
    Error, NP6_CONTEXT_TOKENS, PagedQwenGguf, QWEN3_EMBEDDING_LENGTH, QWEN3_FFN_LENGTH,
    QWEN3_KV_LENGTH, QWEN3_Q_HEADS, QWEN3_Q_LENGTH, QwenBlock0Workspace, ReadAt, StageSummary,
    execute_qwen3_block0_np6,
};
use sha2::{Digest, Sha256};

#[cfg(windows)]
use std::os::windows::fs::FileExt;

const CACHE_BYTES: usize = 1024 * 1024;

struct FileSource {
    file: File,
    size: u64,
    cache: Vec<u8>,
    cache_offset: u64,
    cache_length: usize,
    reads: u64,
    loaded: u64,
}

impl FileSource {
    fn open(path: &PathBuf) -> io::Result<Self> {
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

fn show(name: &str, value: StageSummary) {
    println!(
        "STAGE|{}|{}|{:.17}|{:.17}|{:.9}|{:.9}",
        name, value.values, value.sum_f64, value.square_sum_f64, value.minimum, value.maximum
    );
}

fn main() {
    if let Err(error) = run() {
        eprintln!("BLOCK0_HOST_ERROR={error:?}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Error> {
    let model = env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or(Error::Missing)?;
    let mut source = FileSource::open(&model).map_err(|_| Error::Source)?;
    let gguf = PagedQwenGguf::parse(&mut source)?;
    let tensors = gguf.block0_tensors(&mut source)?;
    let embedding = gguf.tensor(&mut source, "token_embd.weight")?;
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
    let receipt = execute_qwen3_block0_np6(
        &mut source,
        &gguf,
        tensors,
        embedding,
        [49_242, 8_763],
        2,
        &mut workspace,
    )?;
    println!("TOKENS_COMPLETED={}", receipt.tokens_completed);
    println!("DESCRIPTORS_SCANNED={}", receipt.descriptors_scanned);
    println!("MATVEC_CALLS={}", receipt.work.matvec_calls);
    println!("QUANTIZED_BLOCKS={}", receipt.work.quantized_blocks);
    println!("WEIGHT_BYTES_READ={}", receipt.work.weight_bytes_read);
    println!("MULTIPLY_ACCUMULATES={}", receipt.work.multiply_accumulates);
    println!("CACHE_LOADS={}", source.reads);
    println!("CACHE_BYTES_LOADED={}", source.loaded);
    let mut digest = Sha256::new();
    for token in 0..NP6_CONTEXT_TOKENS {
        let mut token_digest = Sha256::new();
        for value in
            &workspace.outputs[token * QWEN3_EMBEDDING_LENGTH..(token + 1) * QWEN3_EMBEDDING_LENGTH]
        {
            token_digest.update(value.to_le_bytes());
            digest.update(value.to_le_bytes());
        }
        println!("OUTPUT_TOKEN_{token}_SHA256={:x}", token_digest.finalize());
    }
    println!("OUTPUT_SHA256={:x}", digest.finalize());
    for (position, token) in receipt.token.into_iter().enumerate() {
        let prefix = format!("token_{position}");
        show(&format!("{prefix}.embedding"), token.embedding);
        show(&format!("{prefix}.attn_norm"), token.attn_norm);
        show(
            &format!("{prefix}.query_projection"),
            token.query_projection,
        );
        show(&format!("{prefix}.key_projection"), token.key_projection);
        show(
            &format!("{prefix}.value_projection"),
            token.value_projection,
        );
        show(&format!("{prefix}.query_norm"), token.query_norm);
        show(&format!("{prefix}.key_norm"), token.key_norm);
        show(&format!("{prefix}.query_rope"), token.query_rope);
        show(&format!("{prefix}.key_rope"), token.key_rope);
        show(
            &format!("{prefix}.attention_weights"),
            token.attention_weights,
        );
        show(
            &format!("{prefix}.attention_context"),
            token.attention_context,
        );
        show(
            &format!("{prefix}.attention_projection"),
            token.attention_projection,
        );
        show(
            &format!("{prefix}.attention_residual"),
            token.attention_residual,
        );
        show(&format!("{prefix}.ffn_norm"), token.ffn_norm);
        show(&format!("{prefix}.ffn_gate"), token.ffn_gate);
        show(&format!("{prefix}.ffn_up"), token.ffn_up);
        show(&format!("{prefix}.ffn_activated"), token.ffn_activated);
        show(&format!("{prefix}.ffn_down"), token.ffn_down);
        show(&format!("{prefix}.block_output"), token.block_output);
    }
    Ok(())
}
