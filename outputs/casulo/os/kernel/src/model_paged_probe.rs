//! NP4 proof that the guest can inspect authentic pages of the complete owner
//! GGUF without copying the multi-gigabyte model into the kernel image/heap.

use casulo_native_model::{
    Error as ModelError, GGML_TYPE_Q4_K, GGML_TYPE_Q6_K, PagedQwenGguf, Q4_K_BLOCK_BYTES,
    Q6_K_BLOCK_BYTES, ReadAt, deterministic_probe_input, dot_q4_k_block, dot_q6_k_block,
    f32_tensor_prefix,
};
use sha2::{Digest, Sha256};

use crate::fw_cfg::{self, ReadStats};
use crate::memory::MemorySummary;

pub const EXPECTED_MODEL_BYTES: u64 = 2_497_280_256;
pub const EXPECTED_MODEL_SHA256: &str =
    "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5";
const EXPECTED_TENSOR_COUNT: u64 = 398;
const EXPECTED_METADATA_COUNT: u64 = 28;
const EXPECTED_DATA_OFFSET: u64 = 5_956_352;
const EXPECTED_Q4_HASH: &str = "5a763d78bb68a51dd06cfef027f366843d18e98500c4c60297c6e929ad278e35";
const EXPECTED_Q6_HASH: &str = "ff1b632d749773aa0fbd6b89ea7108f9f849dc68113fef9fba1d8cc3bbee3182";
const EXPECTED_F32_HASH: &str = "f659212f7856a9a361f9c12713530ea3c75f7c57eb248323c8519dc3767d3ca0";
const EXPECTED_TAIL_HASH: &str = "99444a172fd020304acb41e13fbee447489527621c29330b02ea1b7788a43afb";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Reject {
    Transport(fw_cfg::Reject),
    Gguf(ModelError),
    Header,
    Config,
    Tensor,
    Hash,
    Numeric,
    Adversarial,
}

impl From<fw_cfg::Reject> for Reject {
    fn from(value: fw_cfg::Reject) -> Self {
        Self::Transport(value)
    }
}

impl From<ModelError> for Reject {
    fn from(value: ModelError) -> Self {
        Self::Gguf(value)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Receipt {
    pub source_bytes: u64,
    pub gguf_version: u32,
    pub metadata_count: u64,
    pub tensor_count: u64,
    pub data_offset: u64,
    pub q4_absolute_offset: u64,
    pub q6_absolute_offset: u64,
    pub f32_absolute_offset: u64,
    pub q4_dot_bits: u32,
    pub q6_dot_bits: u32,
    pub tail_offset: u64,
    pub stats: ReadStats,
    pub local_corruption_quarantined: bool,
    pub out_of_bounds_quarantined: bool,
}

pub fn run(memory: &mut MemorySummary) -> Result<Receipt, Reject> {
    let mut source = fw_cfg::ModelFile::open(memory, EXPECTED_MODEL_BYTES)?;
    let gguf = PagedQwenGguf::parse(&mut source)?;
    let header = gguf.header();
    if header.version != 3
        || header.metadata_count != EXPECTED_METADATA_COUNT
        || header.tensor_count != EXPECTED_TENSOR_COUNT
        || header.data_offset != EXPECTED_DATA_OFFSET
        || header.source_len != EXPECTED_MODEL_BYTES
    {
        return Err(Reject::Header);
    }
    let config = gguf.config();
    if config.context_length != 40_960
        || config.embedding_length != 2_560
        || config.feed_forward_length != 9_728
        || config.block_count != 36
        || config.head_count != 32
        || config.head_count_kv != 8
        || config.rope_frequency_base.to_bits() != 1_000_000.0f32.to_bits()
        || config.rms_epsilon.to_bits() != 1e-6f32.to_bits()
    {
        return Err(Reject::Config);
    }

    let f32_tensor = gguf.tensor(&mut source, "output_norm.weight")?;
    let q6_tensor = gguf.tensor(&mut source, "token_embd.weight")?;
    let q4_tensor = gguf.tensor(&mut source, "blk.0.attn_k.weight")?;
    if f32_tensor.ggml_type != 0
        || f32_tensor.dimensions[..f32_tensor.dimension_count as usize] != [2_560]
        || f32_tensor.absolute_offset != 5_956_352
        || q6_tensor.ggml_type != GGML_TYPE_Q6_K
        || q6_tensor.dimensions[..q6_tensor.dimension_count as usize] != [2_560, 151_936]
        || q6_tensor.absolute_offset != 5_966_592
        || q4_tensor.ggml_type != GGML_TYPE_Q4_K
        || q4_tensor.dimensions[..q4_tensor.dimension_count as usize] != [2_560, 1_024]
        || q4_tensor.absolute_offset != 325_032_192
    {
        return Err(Reject::Tensor);
    }

    let mut f32_prefix = [0u8; 64];
    let mut q4_block = [0u8; Q4_K_BLOCK_BYTES];
    let mut q6_block = [0u8; Q6_K_BLOCK_BYTES];
    let mut tail = [0u8; 64];
    source.read_exact_at(f32_tensor.absolute_offset, &mut f32_prefix)?;
    source.read_exact_at(q4_tensor.absolute_offset, &mut q4_block)?;
    source.read_exact_at(q6_tensor.absolute_offset, &mut q6_block)?;
    let tail_offset = EXPECTED_MODEL_BYTES - tail.len() as u64;
    source.read_exact_at(tail_offset, &mut tail)?;
    if !hash_matches(&f32_prefix, EXPECTED_F32_HASH)
        || !hash_matches(&q4_block, EXPECTED_Q4_HASH)
        || !hash_matches(&q6_block, EXPECTED_Q6_HASH)
        || !hash_matches(&tail, EXPECTED_TAIL_HASH)
    {
        return Err(Reject::Hash);
    }

    let mut f32_values = [0.0f32; 16];
    f32_tensor_prefix(&f32_prefix, &mut f32_values)?;
    let input = deterministic_probe_input();
    let q4_dot_bits = dot_q4_k_block(&q4_block, &input)?.to_bits();
    let q6_dot_bits = dot_q6_k_block(&q6_block, &input)?.to_bits();
    if q4_dot_bits != 0x3e29_4826 || q6_dot_bits != 0xbc70_5310 {
        return Err(Reject::Numeric);
    }

    let mut corrupted = q4_block;
    corrupted[16] ^= 1;
    let local_corruption_quarantined = !hash_matches(&corrupted, EXPECTED_Q4_HASH);
    let mut beyond = [0u8; 65];
    let out_of_bounds_quarantined = source
        .read_exact_at(EXPECTED_MODEL_BYTES - 64, &mut beyond)
        .is_err();
    if !local_corruption_quarantined || !out_of_bounds_quarantined {
        return Err(Reject::Adversarial);
    }
    let stats = source.stats();
    if stats.largest_requested_end != EXPECTED_MODEL_BYTES {
        return Err(Reject::Adversarial);
    }

    Ok(Receipt {
        source_bytes: EXPECTED_MODEL_BYTES,
        gguf_version: header.version,
        metadata_count: header.metadata_count,
        tensor_count: header.tensor_count,
        data_offset: header.data_offset,
        q4_absolute_offset: q4_tensor.absolute_offset,
        q6_absolute_offset: q6_tensor.absolute_offset,
        f32_absolute_offset: f32_tensor.absolute_offset,
        q4_dot_bits,
        q6_dot_bits,
        tail_offset,
        stats,
        local_corruption_quarantined,
        out_of_bounds_quarantined,
    })
}

fn hash_matches(bytes: &[u8], expected: &str) -> bool {
    let observed: [u8; 32] = Sha256::digest(bytes).into();
    if expected.len() != 64 {
        return false;
    }
    observed.iter().enumerate().all(|(index, byte)| {
        decode_hex(
            expected.as_bytes()[index * 2],
            expected.as_bytes()[index * 2 + 1],
        ) == Some(*byte)
    })
}

fn decode_hex(high: u8, low: u8) -> Option<u8> {
    fn nibble(value: u8) -> Option<u8> {
        match value {
            b'0'..=b'9' => Some(value - b'0'),
            b'a'..=b'f' => Some(value - b'a' + 10),
            b'A'..=b'F' => Some(value - b'A' + 10),
            _ => None,
        }
    }
    Some((nibble(high)? << 4) | nibble(low)?)
}
