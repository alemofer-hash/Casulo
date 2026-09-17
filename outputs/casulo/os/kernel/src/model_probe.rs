//! Verification of the bounded GGUF/Q4_K projection admitted by the system pack.
//!
//! The projection contains one authentic quantized block plus content-addressed
//! provenance for the adopted Qwen model. Passing this gate proves model-weight
//! consumption and one real quantized primitive. It does not prove a decoder,
//! logits or a model-derived token.

use casulo_native_model::{
    Error as GgufError, GGML_TYPE_Q4_K, GGML_TYPE_Q6_K, Gguf, Q4_K_BLOCK_BYTES, Q6_K_BLOCK_BYTES,
    QwenConfig, deterministic_probe_input, dot_q4_k_block, dot_q6_k_block, f32_tensor_prefix,
};
use sha2::{Digest, Sha256};

pub const EXPECTED_MODEL_SHA256: &str =
    "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5";
pub const EXPECTED_MODEL_BYTES: u64 = 2_497_280_256;
pub const PROJECTION_TENSOR: &str = "casulo.probe.q4_k";

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Reject {
    Gguf(GgufError),
    SourceModel,
    SourceBytes,
    SourceTensor,
    Tensor,
    BlockHash,
    Q6Tensor,
    Q6BlockHash,
    F32Tensor,
    F32Hash,
    ExpectedDot,
    Dot,
    Q6Dot,
}

impl From<GgufError> for Reject {
    fn from(value: GgufError) -> Self {
        Self::Gguf(value)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Receipt<'a> {
    pub gguf_version: u32,
    pub metadata_count: u64,
    pub tensor_count: u64,
    pub source_model_bytes: u64,
    pub source_tensor: &'a str,
    pub source_tensor_offset: u64,
    pub block_bytes: usize,
    pub dot_f32_bits: u32,
    pub expected_dot_f32_bits: u32,
    pub source_q6_tensor: &'a str,
    pub source_q6_tensor_offset: u64,
    pub q6_block_bytes: usize,
    pub q6_dot_f32_bits: u32,
    pub expected_q6_dot_f32_bits: u32,
    pub source_f32_tensor: &'a str,
    pub source_f32_tensor_offset: u64,
    pub f32_values: usize,
    pub config: QwenConfig,
}

pub fn run(bytes: &[u8]) -> Result<Receipt<'_>, Reject> {
    let gguf = Gguf::parse(bytes)?;
    if gguf.string("casulo.source_model_sha256")? != EXPECTED_MODEL_SHA256 {
        return Err(Reject::SourceModel);
    }
    let source_model_bytes = gguf.u64("casulo.source_model_bytes")?;
    if source_model_bytes != EXPECTED_MODEL_BYTES {
        return Err(Reject::SourceBytes);
    }
    let source_tensor = gguf.string("casulo.source_tensor_name")?;
    if source_tensor.is_empty() {
        return Err(Reject::SourceTensor);
    }
    let source_tensor_offset = gguf.u64("casulo.source_tensor_offset")?;
    let tensor = gguf.tensor(PROJECTION_TENSOR)?;
    if tensor.ggml_type != GGML_TYPE_Q4_K || tensor.byte_len != Q4_K_BLOCK_BYTES {
        return Err(Reject::Tensor);
    }
    let block = gguf.tensor_data(tensor)?;
    let observed_block: [u8; 32] = Sha256::digest(block).into();
    if !digest_matches_hex(&observed_block, gguf.string("casulo.source_block_sha256")?) {
        return Err(Reject::BlockHash);
    }
    let input = deterministic_probe_input();
    let dot = dot_q4_k_block(block, &input)?;
    let expected = gguf.f32("casulo.probe_dot_f32")?;
    let expected_bits =
        parse_hex_u32(gguf.string("casulo.probe_dot_f32_bits")?).ok_or(Reject::ExpectedDot)?;
    if expected.to_bits() != expected_bits {
        return Err(Reject::ExpectedDot);
    }
    let delta = if dot >= expected {
        dot - expected
    } else {
        expected - dot
    };
    if !dot.is_finite() || delta > 0.000_01 {
        return Err(Reject::Dot);
    }
    let source_q6_tensor = gguf.string("casulo.source_q6_tensor_name")?;
    let source_q6_tensor_offset = gguf.u64("casulo.source_q6_tensor_offset")?;
    let tensor_q6 = gguf.tensor("casulo.probe.q6_k")?;
    if tensor_q6.ggml_type != GGML_TYPE_Q6_K || tensor_q6.byte_len != Q6_K_BLOCK_BYTES {
        return Err(Reject::Q6Tensor);
    }
    let block_q6 = gguf.tensor_data(tensor_q6)?;
    let observed_q6: [u8; 32] = Sha256::digest(block_q6).into();
    if !digest_matches_hex(&observed_q6, gguf.string("casulo.source_q6_block_sha256")?) {
        return Err(Reject::Q6BlockHash);
    }
    let dot_q6 = dot_q6_k_block(block_q6, &input)?;
    let expected_q6 = gguf.f32("casulo.probe_q6_dot_f32")?;
    let expected_q6_bits =
        parse_hex_u32(gguf.string("casulo.probe_q6_dot_f32_bits")?).ok_or(Reject::ExpectedDot)?;
    if expected_q6.to_bits() != expected_q6_bits {
        return Err(Reject::ExpectedDot);
    }
    let q6_delta = if dot_q6 >= expected_q6 {
        dot_q6 - expected_q6
    } else {
        expected_q6 - dot_q6
    };
    if !dot_q6.is_finite() || q6_delta > 0.000_1 {
        return Err(Reject::Q6Dot);
    }
    let source_f32_tensor = gguf.string("casulo.source_f32_tensor_name")?;
    let source_f32_tensor_offset = gguf.u64("casulo.source_f32_tensor_offset")?;
    let tensor_f32 = gguf.tensor("casulo.probe.f32")?;
    if tensor_f32.ggml_type != 0 || tensor_f32.byte_len != 64 {
        return Err(Reject::F32Tensor);
    }
    let f32_data = gguf.tensor_data(tensor_f32)?;
    let observed_f32: [u8; 32] = Sha256::digest(f32_data).into();
    if !digest_matches_hex(
        &observed_f32,
        gguf.string("casulo.source_f32_prefix_sha256")?,
    ) {
        return Err(Reject::F32Hash);
    }
    let mut f32_values = [0.0f32; 16];
    f32_tensor_prefix(f32_data, &mut f32_values)?;
    let header = gguf.header();
    Ok(Receipt {
        gguf_version: header.version,
        metadata_count: header.metadata_count,
        tensor_count: header.tensor_count,
        source_model_bytes,
        source_tensor,
        source_tensor_offset,
        block_bytes: block.len(),
        dot_f32_bits: dot.to_bits(),
        expected_dot_f32_bits: expected_bits,
        source_q6_tensor,
        source_q6_tensor_offset,
        q6_block_bytes: block_q6.len(),
        q6_dot_f32_bits: dot_q6.to_bits(),
        expected_q6_dot_f32_bits: expected_q6_bits,
        source_f32_tensor,
        source_f32_tensor_offset,
        f32_values: f32_values.len(),
        config: gguf.qwen_config()?,
    })
}

fn digest_matches_hex(digest: &[u8; 32], expected: &str) -> bool {
    let bytes = expected.as_bytes();
    bytes.len() == 64
        && digest.iter().enumerate().all(|(index, byte)| {
            decode_hex(bytes[index * 2]) == Some(byte >> 4)
                && decode_hex(bytes[index * 2 + 1]) == Some(byte & 0x0f)
        })
}

fn parse_hex_u32(value: &str) -> Option<u32> {
    if value.len() != 8 {
        return None;
    }
    let mut output = 0u32;
    for byte in value.bytes() {
        output = output.checked_mul(16)?;
        output = output.checked_add(u32::from(decode_hex(byte)?))?;
    }
    Some(output)
}

fn decode_hex(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}
