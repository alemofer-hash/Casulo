#[path = "decoder_host.rs"]
mod decoder_host;

use std::env;
use std::path::PathBuf;
use std::time::Instant;

use casulo_native_model::{
    Error, NP7_MAX_CONTEXT_TOKENS, PagedQwenGguf, QWEN3_EMBEDDING_LENGTH, QWEN3_FFN_LENGTH,
    QWEN3_KV_LENGTH, QWEN3_Q_HEADS, QWEN3_Q_LENGTH, QwenBlock0Workspace, execute_qwen3_block_np7,
    quantized_matvec, read_f32_vector, read_q6_k_embedding_row, rms_norm,
};
use decoder_host::FileSource;
use sha2::{Digest, Sha256};

const INPUT_TOKEN_ID: u32 = 49_242;
const TOKENS: usize = 4;

fn main() {
    if let Err(error) = run() {
        eprintln!("INCREMENTAL_HOST_ERROR={error:?}");
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
    let layers = config.block_count as usize;

    let mut state = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut norm = vec![0.0; QWEN3_EMBEDDING_LENGTH];
    let mut query = vec![0.0; QWEN3_Q_LENGTH];
    let mut key_cache = vec![0.0; layers * NP7_MAX_CONTEXT_TOKENS * QWEN3_KV_LENGTH];
    let mut value_cache = vec![0.0; layers * NP7_MAX_CONTEXT_TOKENS * QWEN3_KV_LENGTH];
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
    let mut logits = vec![0.0f32; embedding.dimensions[1] as usize];
    let mut token_ids = [0u32; TOKENS];
    token_ids[0] = INPUT_TOKEN_ID;

    for position in 0..TOKENS {
        let token_started = Instant::now();
        let token_id = token_ids[position];
        read_q6_k_embedding_row(&mut source, embedding, token_id, &mut state)?;
        let mut hidden_digest = Sha256::new();
        for block_index in 0..config.block_count {
            let layer_start = block_index as usize * NP7_MAX_CONTEXT_TOKENS * QWEN3_KV_LENGTH;
            let layer_end = layer_start + NP7_MAX_CONTEXT_TOKENS * QWEN3_KV_LENGTH;
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
        read_f32_vector(&mut source, output_norm, &mut attn_norm_weight)?;
        rms_norm(&state, &attn_norm_weight, config.rms_epsilon, &mut norm)?;
        casulo_native_model::quantized_matvec_q8_k_packed(
            &mut source,
            embedding,
            &norm,
            &mut logits,
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
        let tokenizer = gguf.tokenizer(&mut source)?;
        let mut text = [0u8; 64];
        let text_len = tokenizer.token_text(&mut source, greedy as u32, &mut text)?;
        println!("TOKEN_POSITION={position}");
        println!("TOKEN_INPUT_ID={token_id}");
        println!("TOKEN_GREEDY_ID={greedy}");
        if position == 3 {
            println!("TOKEN_REFERENCE_501_LOGIT={:.9}", logits[501]);
            println!("TOKEN_ALTERNATIVE_943_LOGIT={:.9}", logits[943]);
        }
        println!("TOKEN_TEXT_HEX={}", hex(&text[..text_len]));
        println!("TOKEN_HIDDEN_CHAIN_SHA256={:x}", hidden_digest.finalize());
        println!("TOKEN_LOGITS_SHA256={:x}", logits_digest.finalize());
        println!(
            "TOKEN_ELAPSED_MS={:.3}",
            token_started.elapsed().as_secs_f64() * 1000.0
        );
        if position + 1 < TOKENS {
            token_ids[position + 1] = greedy as u32;
        }
    }
    println!("TOKENS_COMPLETED={TOKENS}");
    println!("KV_VALUES={}", layers * TOKENS * QWEN3_KV_LENGTH * 2);
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
