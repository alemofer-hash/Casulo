#[path = "decoder_host.rs"]
mod decoder_host;

use std::env;
use std::path::PathBuf;
use std::time::Instant;

use casulo_native_model::{
    Error, PagedQwenGguf, QWEN3_EMBEDDING_LENGTH, QWEN3_FFN_LENGTH, QWEN3_KV_LENGTH, QWEN3_Q_HEADS,
    QWEN3_Q_LENGTH, QwenBlock0Workspace, execute_qwen3_block_np7, quantized_matvec,
    read_f32_vector, read_q6_k_embedding_row, rms_norm,
};
use decoder_host::FileSource;
use sha2::{Digest, Sha256};

const CONTEXT_CAPACITY: usize = 96;
const MAX_OUTPUT_TOKENS: usize = 40;
const PROMPT_TOKENS: [u32; 50] = [
    151644, 8948, 198, 56450, 13, 1800, 618, 3235, 10608, 47673, 25, 451, 11408, 25387, 26, 62721,
    5049, 46, 25387, 26, 1825, 49, 32293, 25387, 26, 7778, 51171, 25387, 13, 151645, 198, 151644,
    872, 198, 34, 7231, 25, 1045, 50341, 55626, 13, 151645, 198, 151644, 77091, 198, 151667, 271,
    151668, 271,
];
const EXPECTED_OUTPUT_TOKENS: [u32; 34] = [
    45, 11408, 28, 8373, 5404, 285, 67737, 436, 26, 62721, 5049, 46, 28, 8373, 5404, 285, 67737,
    436, 26, 1825, 49, 32293, 28, 32615, 16, 11, 32615, 17, 26, 7778, 51171, 28, 32361, 13,
];

fn main() {
    if let Err(error) = run() {
        eprintln!("CREATION_HOST_ERROR={error:?}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Error> {
    let model = env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or(Error::Missing)?;
    let max_output_tokens = env::args()
        .nth(2)
        .map(|value| value.parse::<usize>().map_err(|_| Error::Mismatch))
        .transpose()?
        .unwrap_or(MAX_OUTPUT_TOKENS);
    let prompt_token_count = env::args()
        .nth(3)
        .map(|value| value.parse::<usize>().map_err(|_| Error::Mismatch))
        .transpose()?
        .unwrap_or(PROMPT_TOKENS.len());
    if !(1..=MAX_OUTPUT_TOKENS).contains(&max_output_tokens) {
        return Err(Error::Bounds);
    }
    if !(1..=PROMPT_TOKENS.len()).contains(&prompt_token_count) {
        return Err(Error::Bounds);
    }
    let started = Instant::now();
    let mut source = FileSource::open(&model).map_err(|_| Error::Source)?;
    let gguf = PagedQwenGguf::parse(&mut source)?;
    let config = gguf.config();
    let embedding = gguf.tensor(&mut source, "token_embd.weight")?;
    let output_norm = gguf.tensor(&mut source, "output_norm.weight")?;
    let layers = config.block_count as usize;

    let mut state = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut norm = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut query = vec![0.0; QWEN3_Q_LENGTH];
    let mut key_cache = vec![0.0; layers * CONTEXT_CAPACITY * QWEN3_KV_LENGTH];
    let mut value_cache = vec![0.0; layers * CONTEXT_CAPACITY * QWEN3_KV_LENGTH];
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
    let mut logits = vec![0.0f32; embedding.dimensions[1] as usize];

    let mut generated = Vec::new();
    let mut next_input = 0u32;
    for position in 0..CONTEXT_CAPACITY {
        let token_id = if position < prompt_token_count {
            PROMPT_TOKENS[position]
        } else {
            next_input
        };
        let token_started = Instant::now();
        read_q6_k_embedding_row(&mut source, embedding, token_id, &mut state)?;
        let mut hidden_digest = Sha256::new();
        for block_index in 0..config.block_count {
            let layer_start = block_index as usize * CONTEXT_CAPACITY * QWEN3_KV_LENGTH;
            let layer_end = layer_start + CONTEXT_CAPACITY * QWEN3_KV_LENGTH;
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
            execute_qwen3_block_np7(
                &mut source,
                &gguf,
                block_index,
                tensors,
                token_id,
                position,
                &mut workspace,
            )?;
            for value in state.iter() {
                hidden_digest.update(value.to_le_bytes());
            }
        }
        if position + 1 < prompt_token_count {
            if position % 10 == 9 {
                println!("PREFILL_POSITIONS_COMPLETED={}", position + 1);
            }
            continue;
        }
        read_f32_vector(&mut source, output_norm, &mut attn_norm_weight)?;
        rms_norm(&state, &attn_norm_weight, config.rms_epsilon, &mut norm)?;
        casulo_native_model::quantized_matvec_q8_k_packed(
            &mut source,
            embedding,
            &norm,
            &mut logits,
        )?;
        let greedy = (1..logits.len()).fold(0usize, |best, index| {
            if logits[index].total_cmp(&logits[best]).is_gt() {
                index
            } else {
                best
            }
        });
        let output_index = generated.len();
        generated.push(greedy as u32);
        let tokenizer = gguf.tokenizer(&mut source)?;
        let mut text = [0u8; 64];
        let text_len = tokenizer.token_text(&mut source, greedy as u32, &mut text)?;
        println!("OUTPUT_{output_index}_ID={greedy}");
        println!("OUTPUT_{output_index}_TEXT_HEX={}", hex(&text[..text_len]));
        println!(
            "OUTPUT_{output_index}_HIDDEN_SHA256={:x}",
            hidden_digest.finalize()
        );
        println!(
            "OUTPUT_{output_index}_ELAPSED_MS={:.3}",
            token_started.elapsed().as_secs_f64() * 1000.0
        );
        next_input = greedy as u32;
        if greedy as u32 == 13 || generated.len() >= max_output_tokens {
            break;
        }
    }
    println!("PROMPT_TOKENS={prompt_token_count}");
    println!("OUTPUT_TOKENS={}", generated.len());
    println!("OUTPUT_IDS={generated:?}");
    println!(
        "LLAMA_CPP_GREEDY_MATCH={}",
        prompt_token_count == PROMPT_TOKENS.len() && generated == EXPECTED_OUTPUT_TOKENS
    );
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
