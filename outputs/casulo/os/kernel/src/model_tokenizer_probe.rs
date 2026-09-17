//! NP5 bounded tokenizer and authentic embedding-row qualification.
//!
//! This gate exercises ordinary ASCII/Latin byte-BPE against frozen offline
//! llama.cpp oracle cases. Chat-template execution and decoder inference stay
//! explicitly outside this gate.

use casulo_native_model::{
    Error as ModelError, PagedQwenGguf, ReadAt, TokenizeReceipt, read_q6_k_embedding_row,
};
use sha2::{Digest, Sha256};

use crate::fw_cfg::{self, ReadStats};
use crate::memory::MemorySummary;
use crate::model_paged_probe::EXPECTED_MODEL_BYTES;

const EXPECTED_TOKENS: u64 = 151_936;
const EXPECTED_MERGES: u64 = 151_387;
const EXPECTED_TOKENS_PAYLOAD: u64 = 831;
const EXPECTED_TOKENS_END: u64 = 2_589_079;
const EXPECTED_TYPES_PAYLOAD: u64 = 2_589_128;
const EXPECTED_TYPES_END: u64 = 3_196_872;
const EXPECTED_MERGES_PAYLOAD: u64 = 3_196_917;
const EXPECTED_MERGES_END: u64 = 5_928_465;
const EXPECTED_CHAT_TEMPLATE_BYTES: u64 = 4_100;
const EXPECTED_TOKENS_HASH: &str =
    "adab67cd4451390df3c68d6b3e74f5095d857769780735c7e7044e571db2a89e";
const EXPECTED_TYPES_HASH: &str =
    "fd28e1c1092285f1de6c3c1d3c78105e1a63f503d7eef2fb8cb00017c05c0979";
const EXPECTED_MERGES_HASH: &str =
    "907981a313a6e78ef2223229042674a39cd4995ee4c4ed40a31b58754e82c26c";
const EXPECTED_CHAT_TEMPLATE_HASH: &str =
    "57f1fd00f0013a2be96aa79b857391f27e23df5b5f847072b524c897e24d0361";
const EXPECTED_EMBEDDING_RAW_HASH: &str =
    "3ba52dc117730ee5d8533687c629c39fa66b96aa6de98a6361e427ccc956886b";
const EXPECTED_EMBEDDING_F32_HASH: &str =
    "3007f5b6e6517db829162dfdfe541d1762cb72ce23676453006db25b699b2d7f";
const EXPECTED_FIRST_BITS: [u32; 8] = [
    0x3ad4_5000,
    0x3cd4_5000,
    0x3b9f_3c00,
    0x3cee_da00,
    0x3c6e_da00,
    0xbd2c_8100,
    0x3d40_6880,
    0x3d47_0b00,
];
const EXPECTED_SUM_BITS: u32 = 0x3f7e_76a4;
const EMBEDDING_TOKEN_ID: u32 = 49_242;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Reject {
    Transport(fw_cfg::Reject),
    Model(ModelError),
    Metadata,
    TokenizerHash,
    Tokenization,
    Embedding,
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Receipt {
    pub token_count: u64,
    pub merge_count: u64,
    pub bos_token_id: u32,
    pub eos_token_id: u32,
    pub padding_token_id: u32,
    pub chat_template_bytes: u64,
    pub casulo: TokenizeReceipt,
    pub hello_world: TokenizeReceipt,
    pub ola_casulo: TokenizeReceipt,
    pub embedding_token_id: u32,
    pub embedding_row_offset: u64,
    pub embedding_row_bytes: u32,
    pub embedding_sum_bits: u32,
    pub unsupported_special_rejected: bool,
    pub unsupported_script_rejected: bool,
    pub invalid_token_rejected: bool,
    pub stats: ReadStats,
}

pub fn run(memory: &mut MemorySummary) -> Result<Receipt, Reject> {
    let mut source = fw_cfg::ModelFile::open(memory, EXPECTED_MODEL_BYTES)?;
    let gguf = PagedQwenGguf::parse(&mut source)?;
    let tokenizer = gguf.tokenizer(&mut source)?;
    if tokenizer.tokens.count != EXPECTED_TOKENS
        || tokenizer.tokens.payload_offset != EXPECTED_TOKENS_PAYLOAD
        || tokenizer.tokens.end_offset != EXPECTED_TOKENS_END
        || tokenizer.token_types.count != EXPECTED_TOKENS
        || tokenizer.token_types.element_type != 5
        || tokenizer.token_types.payload_offset != EXPECTED_TYPES_PAYLOAD
        || tokenizer.token_types.end_offset != EXPECTED_TYPES_END
        || tokenizer.merges.count != EXPECTED_MERGES
        || tokenizer.merges.payload_offset != EXPECTED_MERGES_PAYLOAD
        || tokenizer.merges.end_offset != EXPECTED_MERGES_END
        || tokenizer.chat_template.byte_len != EXPECTED_CHAT_TEMPLATE_BYTES
        || tokenizer.bos_token_id != 151_643
        || tokenizer.eos_token_id != 151_645
        || tokenizer.padding_token_id != 151_643
        || tokenizer.add_bos_token
    {
        return Err(Reject::Metadata);
    }
    if !hash_region_matches(
        &mut source,
        tokenizer.tokens.payload_offset,
        tokenizer.tokens.end_offset,
        EXPECTED_TOKENS_HASH,
    )? || !hash_region_matches(
        &mut source,
        tokenizer.token_types.payload_offset,
        tokenizer.token_types.end_offset,
        EXPECTED_TYPES_HASH,
    )? || !hash_region_matches(
        &mut source,
        tokenizer.merges.payload_offset,
        tokenizer.merges.end_offset,
        EXPECTED_MERGES_HASH,
    )? || !hash_region_matches(
        &mut source,
        tokenizer.chat_template.offset,
        tokenizer.chat_template.offset + tokenizer.chat_template.byte_len,
        EXPECTED_CHAT_TEMPLATE_HASH,
    )? {
        return Err(Reject::TokenizerHash);
    }

    let mut ids = [0u32; 16];
    let casulo = tokenizer.tokenize_basic(&mut source, b"Casulo", &mut ids)?;
    if &ids[..casulo.output_tokens as usize] != [49_242, 8_763] {
        return Err(Reject::Tokenization);
    }
    let hello_world = tokenizer.tokenize_basic(&mut source, b"hello world", &mut ids)?;
    if &ids[..hello_world.output_tokens as usize] != [14_990, 1_879] {
        return Err(Reject::Tokenization);
    }
    let ola_casulo = tokenizer.tokenize_basic(&mut source, "Olá, Casulo.".as_bytes(), &mut ids)?;
    if &ids[..ola_casulo.output_tokens as usize] != [42_719, 1_953, 11, 11_054, 8_763, 13] {
        return Err(Reject::Tokenization);
    }

    let unsupported_special_rejected = tokenizer
        .tokenize_basic(&mut source, b"<|im_start|>", &mut ids)
        .is_err();
    let unsupported_script_rejected = tokenizer
        .tokenize_basic(&mut source, "漢".as_bytes(), &mut ids)
        .is_err();

    let embedding = gguf.tensor(&mut source, "token_embd.weight")?;
    let mut vector = [0.0f32; 2_560];
    let embedding_receipt =
        read_q6_k_embedding_row(&mut source, embedding, EMBEDDING_TOKEN_ID, &mut vector)?;
    if embedding_receipt.row_offset != 109_374_792
        || embedding_receipt.row_bytes != 2_100
        || embedding_receipt.decoded_values != 2_560
        || vector[..8]
            .iter()
            .zip(EXPECTED_FIRST_BITS)
            .any(|(value, expected)| value.to_bits() != expected)
    {
        return Err(Reject::Embedding);
    }
    let mut decoded_hash = Sha256::new();
    let mut sum = 0.0f32;
    for value in vector {
        decoded_hash.update(value.to_le_bytes());
        sum += value;
    }
    if !digest_matches(decoded_hash.finalize().into(), EXPECTED_EMBEDDING_F32_HASH)
        || sum.to_bits() != EXPECTED_SUM_BITS
        || !hash_region_matches(
            &mut source,
            embedding_receipt.row_offset,
            embedding_receipt.row_offset + u64::from(embedding_receipt.row_bytes),
            EXPECTED_EMBEDDING_RAW_HASH,
        )?
    {
        return Err(Reject::Embedding);
    }
    let invalid_token_rejected =
        read_q6_k_embedding_row(&mut source, embedding, EXPECTED_TOKENS as u32, &mut vector)
            .is_err();
    if !unsupported_special_rejected || !unsupported_script_rejected || !invalid_token_rejected {
        return Err(Reject::Adversarial);
    }

    Ok(Receipt {
        token_count: tokenizer.tokens.count,
        merge_count: tokenizer.merges.count,
        bos_token_id: tokenizer.bos_token_id,
        eos_token_id: tokenizer.eos_token_id,
        padding_token_id: tokenizer.padding_token_id,
        chat_template_bytes: tokenizer.chat_template.byte_len,
        casulo,
        hello_world,
        ola_casulo,
        embedding_token_id: embedding_receipt.token_id,
        embedding_row_offset: embedding_receipt.row_offset,
        embedding_row_bytes: embedding_receipt.row_bytes,
        embedding_sum_bits: sum.to_bits(),
        unsupported_special_rejected,
        unsupported_script_rejected,
        invalid_token_rejected,
        stats: source.stats(),
    })
}

fn hash_region_matches<R: ReadAt>(
    source: &mut R,
    start: u64,
    end: u64,
    expected: &str,
) -> Result<bool, ModelError> {
    if end < start || end > source.len() {
        return Err(ModelError::Bounds);
    }
    let mut digest = Sha256::new();
    let mut offset = start;
    let mut buffer = [0u8; 512];
    while offset < end {
        let length = usize::try_from((end - offset).min(buffer.len() as u64))
            .map_err(|_| ModelError::Bounds)?;
        source.read_exact_at(offset, &mut buffer[..length])?;
        digest.update(&buffer[..length]);
        offset += length as u64;
    }
    Ok(digest_matches(digest.finalize().into(), expected))
}

fn digest_matches(observed: [u8; 32], expected: &str) -> bool {
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

pub const ORACLE_RUNTIME_SHA256: &str =
    "4b63587d19ac1fecabce65aa4e7da41212865cb323804882b9f68ed44a5ec573";
