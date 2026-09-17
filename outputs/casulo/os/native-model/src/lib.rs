#![no_std]

//! Bounded GGUF metadata/tensor reader and low-level neural primitives.
//!
//! This crate is deliberately free of filesystem, process, network and model
//! policy. It validates bytes already admitted by the capability layer. A
//! successful parse or quantized operation is not, by itself, token inference.

pub const GGUF_MAGIC: &[u8; 4] = b"GGUF";
pub const GGUF_VERSION_3: u32 = 3;
pub const GGML_TYPE_Q4_K: u32 = 12;
pub const GGML_TYPE_Q6_K: u32 = 14;
pub const QK_K: usize = 256;
pub const Q4_K_BLOCK_BYTES: usize = 144;
pub const Q6_K_BLOCK_BYTES: usize = 210;

const MAX_METADATA: u64 = 65_536;
const MAX_TENSORS: u64 = 65_536;
const MAX_NAME_BYTES: u64 = 4_096;
const MAX_ARRAY_ITEMS: u64 = 16_777_216;
const MAX_NESTING: u8 = 3;
const DEFAULT_ALIGNMENT: u32 = 32;

const TYPE_U8: u32 = 0;
const TYPE_I8: u32 = 1;
const TYPE_U16: u32 = 2;
const TYPE_I16: u32 = 3;
const TYPE_U32: u32 = 4;
const TYPE_I32: u32 = 5;
const TYPE_F32: u32 = 6;
const TYPE_BOOL: u32 = 7;
const TYPE_STRING: u32 = 8;
const TYPE_ARRAY: u32 = 9;
const TYPE_U64: u32 = 10;
const TYPE_I64: u32 = 11;
const TYPE_F64: u32 = 12;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Error {
    Source,
    Truncated,
    Magic,
    Version,
    Count,
    Type,
    Bounds,
    Alignment,
    Utf8,
    Missing,
    Mismatch,
    Quantization,
    NonFinite,
    Unsupported,
}

/// Read-only random-access source admitted by the Native capability layer.
///
/// The model crate never opens a file, device or network endpoint. The kernel
/// supplies an already-authorized source and this trait preserves that narrow
/// boundary while allowing a multi-gigabyte GGUF to stay outside the heap.
pub trait ReadAt {
    fn len(&self) -> u64;
    fn read_exact_at(&mut self, offset: u64, output: &mut [u8]) -> Result<(), Error>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Header {
    pub version: u32,
    pub tensor_count: u64,
    pub metadata_count: u64,
    pub tensor_table_offset: usize,
    pub data_offset: usize,
    pub alignment: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TensorInfo<'a> {
    pub name: &'a str,
    pub dimensions: [u64; 4],
    pub dimension_count: u32,
    pub ggml_type: u32,
    pub relative_offset: u64,
    pub absolute_offset: usize,
    pub byte_len: usize,
}

impl TensorInfo<'_> {
    pub fn element_count(&self) -> Result<u64, Error> {
        let mut count = 1u64;
        for dimension in &self.dimensions[..self.dimension_count as usize] {
            count = count.checked_mul(*dimension).ok_or(Error::Bounds)?;
        }
        Ok(count)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct QwenConfig {
    pub context_length: u32,
    pub embedding_length: u32,
    pub feed_forward_length: u32,
    pub block_count: u32,
    pub head_count: u32,
    pub head_count_kv: u32,
    pub rope_frequency_base: f32,
    pub rms_epsilon: f32,
}

#[derive(Clone, Copy)]
pub struct Gguf<'a> {
    bytes: &'a [u8],
    header: Header,
}

impl<'a> Gguf<'a> {
    pub fn parse(bytes: &'a [u8]) -> Result<Self, Error> {
        if bytes.get(..4) != Some(GGUF_MAGIC) {
            return Err(Error::Magic);
        }
        let version = read_u32(bytes, 4)?;
        if version != GGUF_VERSION_3 {
            return Err(Error::Version);
        }
        let tensor_count = read_u64(bytes, 8)?;
        let metadata_count = read_u64(bytes, 16)?;
        if tensor_count == 0
            || tensor_count > MAX_TENSORS
            || metadata_count == 0
            || metadata_count > MAX_METADATA
        {
            return Err(Error::Count);
        }
        let mut cursor = 24usize;
        let mut alignment = DEFAULT_ALIGNMENT;
        for _ in 0..metadata_count {
            let key = read_key(bytes, &mut cursor)?;
            let value_type = take_u32(bytes, &mut cursor)?;
            if key == b"general.alignment" {
                if value_type != TYPE_U32 {
                    return Err(Error::Mismatch);
                }
                alignment = take_u32(bytes, &mut cursor)?;
            } else {
                skip_value(bytes, &mut cursor, value_type, 0)?;
            }
        }
        if alignment == 0 || !alignment.is_power_of_two() || alignment > 4096 {
            return Err(Error::Alignment);
        }
        let tensor_table_offset = cursor;
        for _ in 0..tensor_count {
            let _name = read_key(bytes, &mut cursor)?;
            let dimensions = take_u32(bytes, &mut cursor)?;
            if dimensions == 0 || dimensions > 4 {
                return Err(Error::Bounds);
            }
            advance(bytes, &mut cursor, dimensions as usize * 8)?;
            advance(bytes, &mut cursor, 4 + 8)?;
        }
        let data_offset = align_up(cursor, alignment as usize)?;
        if data_offset > bytes.len() {
            return Err(Error::Truncated);
        }
        Ok(Self {
            bytes,
            header: Header {
                version,
                tensor_count,
                metadata_count,
                tensor_table_offset,
                data_offset,
                alignment,
            },
        })
    }

    pub const fn header(&self) -> Header {
        self.header
    }

    pub fn string(&self, wanted: &str) -> Result<&'a str, Error> {
        let mut cursor = 24usize;
        for _ in 0..self.header.metadata_count {
            let key = read_key(self.bytes, &mut cursor)?;
            let value_type = take_u32(self.bytes, &mut cursor)?;
            if key == wanted.as_bytes() {
                if value_type != TYPE_STRING {
                    return Err(Error::Mismatch);
                }
                return core::str::from_utf8(read_string(self.bytes, &mut cursor)?)
                    .map_err(|_| Error::Utf8);
            }
            skip_value(self.bytes, &mut cursor, value_type, 0)?;
        }
        Err(Error::Missing)
    }

    pub fn u32(&self, wanted: &str) -> Result<u32, Error> {
        self.scalar_u64(wanted, TYPE_U32)
            .and_then(|value| u32::try_from(value).map_err(|_| Error::Bounds))
    }

    pub fn u64(&self, wanted: &str) -> Result<u64, Error> {
        self.scalar_u64(wanted, TYPE_U64)
    }

    pub fn f32(&self, wanted: &str) -> Result<f32, Error> {
        let mut cursor = 24usize;
        for _ in 0..self.header.metadata_count {
            let key = read_key(self.bytes, &mut cursor)?;
            let value_type = take_u32(self.bytes, &mut cursor)?;
            if key == wanted.as_bytes() {
                if value_type != TYPE_F32 {
                    return Err(Error::Mismatch);
                }
                return Ok(f32::from_bits(take_u32(self.bytes, &mut cursor)?));
            }
            skip_value(self.bytes, &mut cursor, value_type, 0)?;
        }
        Err(Error::Missing)
    }

    fn scalar_u64(&self, wanted: &str, expected_type: u32) -> Result<u64, Error> {
        let mut cursor = 24usize;
        for _ in 0..self.header.metadata_count {
            let key = read_key(self.bytes, &mut cursor)?;
            let value_type = take_u32(self.bytes, &mut cursor)?;
            if key == wanted.as_bytes() {
                if value_type != expected_type {
                    return Err(Error::Mismatch);
                }
                return if expected_type == TYPE_U32 {
                    Ok(u64::from(take_u32(self.bytes, &mut cursor)?))
                } else {
                    take_u64(self.bytes, &mut cursor)
                };
            }
            skip_value(self.bytes, &mut cursor, value_type, 0)?;
        }
        Err(Error::Missing)
    }

    pub fn tensor(&self, wanted: &str) -> Result<TensorInfo<'a>, Error> {
        let mut cursor = self.header.tensor_table_offset;
        for _ in 0..self.header.tensor_count {
            let name_bytes = read_key(self.bytes, &mut cursor)?;
            let name = core::str::from_utf8(name_bytes).map_err(|_| Error::Utf8)?;
            let dimension_count = take_u32(self.bytes, &mut cursor)?;
            if dimension_count == 0 || dimension_count > 4 {
                return Err(Error::Bounds);
            }
            let mut dimensions = [0u64; 4];
            for dimension in &mut dimensions[..dimension_count as usize] {
                *dimension = take_u64(self.bytes, &mut cursor)?;
                if *dimension == 0 {
                    return Err(Error::Bounds);
                }
            }
            let ggml_type = take_u32(self.bytes, &mut cursor)?;
            let relative_offset = take_u64(self.bytes, &mut cursor)?;
            if name == wanted {
                let mut info = TensorInfo {
                    name,
                    dimensions,
                    dimension_count,
                    ggml_type,
                    relative_offset,
                    absolute_offset: 0,
                    byte_len: 0,
                };
                let elements = info.element_count()?;
                info.byte_len = tensor_bytes(ggml_type, elements)?;
                let relative = usize::try_from(relative_offset).map_err(|_| Error::Bounds)?;
                info.absolute_offset = self
                    .header
                    .data_offset
                    .checked_add(relative)
                    .ok_or(Error::Bounds)?;
                let end = info
                    .absolute_offset
                    .checked_add(info.byte_len)
                    .ok_or(Error::Bounds)?;
                if end > self.bytes.len() {
                    return Err(Error::Truncated);
                }
                return Ok(info);
            }
        }
        Err(Error::Missing)
    }

    pub fn tensor_data(&self, info: TensorInfo<'_>) -> Result<&'a [u8], Error> {
        let end = info
            .absolute_offset
            .checked_add(info.byte_len)
            .ok_or(Error::Bounds)?;
        self.bytes
            .get(info.absolute_offset..end)
            .ok_or(Error::Truncated)
    }

    pub fn qwen_config(&self) -> Result<QwenConfig, Error> {
        if self.string("general.architecture")? != "qwen3" {
            return Err(Error::Mismatch);
        }
        let config = QwenConfig {
            context_length: self.u32("qwen3.context_length")?,
            embedding_length: self.u32("qwen3.embedding_length")?,
            feed_forward_length: self.u32("qwen3.feed_forward_length")?,
            block_count: self.u32("qwen3.block_count")?,
            head_count: self.u32("qwen3.attention.head_count")?,
            head_count_kv: self.u32("qwen3.attention.head_count_kv")?,
            rope_frequency_base: self.f32("qwen3.rope.freq_base")?,
            rms_epsilon: self.f32("qwen3.attention.layer_norm_rms_epsilon")?,
        };
        if config.context_length == 0
            || config.embedding_length == 0
            || config.feed_forward_length == 0
            || config.block_count == 0
            || config.head_count == 0
            || config.head_count_kv == 0
            || !config.rope_frequency_base.is_finite()
            || !config.rms_epsilon.is_finite()
            || config.rms_epsilon <= 0.0
        {
            return Err(Error::Mismatch);
        }
        Ok(config)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PagedHeader {
    pub version: u32,
    pub tensor_count: u64,
    pub metadata_count: u64,
    pub tensor_table_offset: u64,
    pub data_offset: u64,
    pub alignment: u32,
    pub source_len: u64,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PagedQwenGguf {
    header: PagedHeader,
    config: QwenConfig,
}

impl PagedQwenGguf {
    /// Parse GGUF metadata and the tensor-table boundary without materializing
    /// the file. Variable-sized arrays are traversed only as required by the
    /// GGUF encoding; tensor payload bytes are never copied by this operation.
    pub fn parse<R: ReadAt>(source: &mut R) -> Result<Self, Error> {
        let source_len = source.len();
        let mut cursor = PagedCursor::new(source);
        let mut magic = [0u8; 4];
        cursor.read_exact(&mut magic)?;
        if &magic != GGUF_MAGIC {
            return Err(Error::Magic);
        }
        let version = cursor.take_u32()?;
        if version != GGUF_VERSION_3 {
            return Err(Error::Version);
        }
        let tensor_count = cursor.take_u64()?;
        let metadata_count = cursor.take_u64()?;
        if tensor_count == 0
            || tensor_count > MAX_TENSORS
            || metadata_count == 0
            || metadata_count > MAX_METADATA
        {
            return Err(Error::Count);
        }

        let mut alignment = DEFAULT_ALIGNMENT;
        let mut architecture_qwen3 = false;
        let mut context_length = None;
        let mut embedding_length = None;
        let mut feed_forward_length = None;
        let mut block_count = None;
        let mut head_count = None;
        let mut head_count_kv = None;
        let mut rope_frequency_base = None;
        let mut rms_epsilon = None;

        for _ in 0..metadata_count {
            let key = cursor.take_small_name()?;
            let value_type = cursor.take_u32()?;
            match key.as_bytes() {
                Some(b"general.architecture") => {
                    if value_type != TYPE_STRING {
                        return Err(Error::Mismatch);
                    }
                    architecture_qwen3 = cursor.take_small_name()?.as_bytes() == Some(b"qwen3");
                }
                Some(b"general.alignment") => {
                    if value_type != TYPE_U32 {
                        return Err(Error::Mismatch);
                    }
                    alignment = cursor.take_u32()?;
                }
                Some(b"qwen3.context_length") => {
                    context_length = Some(take_paged_u32(&mut cursor, value_type)?);
                }
                Some(b"qwen3.embedding_length") => {
                    embedding_length = Some(take_paged_u32(&mut cursor, value_type)?);
                }
                Some(b"qwen3.feed_forward_length") => {
                    feed_forward_length = Some(take_paged_u32(&mut cursor, value_type)?);
                }
                Some(b"qwen3.block_count") => {
                    block_count = Some(take_paged_u32(&mut cursor, value_type)?);
                }
                Some(b"qwen3.attention.head_count") => {
                    head_count = Some(take_paged_u32(&mut cursor, value_type)?);
                }
                Some(b"qwen3.attention.head_count_kv") => {
                    head_count_kv = Some(take_paged_u32(&mut cursor, value_type)?);
                }
                Some(b"qwen3.rope.freq_base") => {
                    rope_frequency_base = Some(take_paged_f32(&mut cursor, value_type)?);
                }
                Some(b"qwen3.attention.layer_norm_rms_epsilon") => {
                    rms_epsilon = Some(take_paged_f32(&mut cursor, value_type)?);
                }
                _ => cursor.skip_value(value_type, 0)?,
            }
        }
        if !architecture_qwen3 {
            return Err(Error::Mismatch);
        }
        if alignment == 0 || !alignment.is_power_of_two() || alignment > 4096 {
            return Err(Error::Alignment);
        }
        let tensor_table_offset = cursor.offset;
        for _ in 0..tensor_count {
            cursor.skip_name()?;
            let dimension_count = cursor.take_u32()?;
            if dimension_count == 0 || dimension_count > 4 {
                return Err(Error::Bounds);
            }
            cursor.advance(u64::from(dimension_count) * 8)?;
            cursor.advance(4 + 8)?;
        }
        let data_offset = align_up_u64(cursor.offset, u64::from(alignment))?;
        if data_offset > source_len {
            return Err(Error::Truncated);
        }
        let config = QwenConfig {
            context_length: context_length.ok_or(Error::Missing)?,
            embedding_length: embedding_length.ok_or(Error::Missing)?,
            feed_forward_length: feed_forward_length.ok_or(Error::Missing)?,
            block_count: block_count.ok_or(Error::Missing)?,
            head_count: head_count.ok_or(Error::Missing)?,
            head_count_kv: head_count_kv.ok_or(Error::Missing)?,
            rope_frequency_base: rope_frequency_base.ok_or(Error::Missing)?,
            rms_epsilon: rms_epsilon.ok_or(Error::Missing)?,
        };
        validate_qwen_config(config)?;
        Ok(Self {
            header: PagedHeader {
                version,
                tensor_count,
                metadata_count,
                tensor_table_offset,
                data_offset,
                alignment,
                source_len,
            },
            config,
        })
    }

    pub const fn header(&self) -> PagedHeader {
        self.header
    }

    pub const fn config(&self) -> QwenConfig {
        self.config
    }

    pub fn tensor<R: ReadAt>(
        &self,
        source: &mut R,
        wanted: &str,
    ) -> Result<TensorDescriptor, Error> {
        let mut cursor = PagedCursor::at(source, self.header.tensor_table_offset)?;
        for _ in 0..self.header.tensor_count {
            let name = cursor.take_small_name()?;
            let dimension_count = cursor.take_u32()?;
            if dimension_count == 0 || dimension_count > 4 {
                return Err(Error::Bounds);
            }
            let mut dimensions = [0u64; 4];
            for dimension in &mut dimensions[..dimension_count as usize] {
                *dimension = cursor.take_u64()?;
                if *dimension == 0 {
                    return Err(Error::Bounds);
                }
            }
            let ggml_type = cursor.take_u32()?;
            let relative_offset = cursor.take_u64()?;
            if name.as_bytes() == Some(wanted.as_bytes()) {
                let mut elements = 1u64;
                for dimension in &dimensions[..dimension_count as usize] {
                    elements = elements.checked_mul(*dimension).ok_or(Error::Bounds)?;
                }
                let byte_len =
                    u64::try_from(tensor_bytes(ggml_type, elements)?).map_err(|_| Error::Bounds)?;
                let absolute_offset = self
                    .header
                    .data_offset
                    .checked_add(relative_offset)
                    .ok_or(Error::Bounds)?;
                let end = absolute_offset.checked_add(byte_len).ok_or(Error::Bounds)?;
                if end > self.header.source_len {
                    return Err(Error::Truncated);
                }
                return Ok(TensorDescriptor {
                    dimensions,
                    dimension_count,
                    ggml_type,
                    relative_offset,
                    absolute_offset,
                    byte_len,
                });
            }
        }
        Err(Error::Missing)
    }

    /// Preserve the NP6 block-zero API while routing it through the general
    /// bounded block index introduced for NP7.
    pub fn block0_tensors<R: ReadAt>(&self, source: &mut R) -> Result<QwenBlock0Tensors, Error> {
        self.block_tensors(source, 0)
    }

    /// Resolve every tensor required by one Qwen3 block in one bounded scan of
    /// the GGUF tensor table. The block number is interpreted structurally;
    /// no heap allocation or formatted tensor name is needed in `no_std`.
    pub fn block_tensors<R: ReadAt>(
        &self,
        source: &mut R,
        block_index: u32,
    ) -> Result<QwenBlock0Tensors, Error> {
        if block_index >= self.config.block_count {
            return Err(Error::Bounds);
        }
        let mut cursor = PagedCursor::at(source, self.header.tensor_table_offset)?;
        let mut attn_k = None;
        let mut attn_k_norm = None;
        let mut attn_norm = None;
        let mut attn_output = None;
        let mut attn_q = None;
        let mut attn_q_norm = None;
        let mut attn_v = None;
        let mut ffn_down = None;
        let mut ffn_gate = None;
        let mut ffn_norm = None;
        let mut ffn_up = None;
        let mut scanned = 0u32;
        for _ in 0..self.header.tensor_count {
            let name = cursor.take_small_name()?;
            let dimension_count = cursor.take_u32()?;
            if dimension_count == 0 || dimension_count > 4 {
                return Err(Error::Bounds);
            }
            let mut dimensions = [0u64; 4];
            for dimension in &mut dimensions[..dimension_count as usize] {
                *dimension = cursor.take_u64()?;
                if *dimension == 0 {
                    return Err(Error::Bounds);
                }
            }
            let ggml_type = cursor.take_u32()?;
            let relative_offset = cursor.take_u64()?;
            scanned = scanned.checked_add(1).ok_or(Error::Bounds)?;
            let Some(name_bytes) = name.as_bytes() else {
                continue;
            };
            let Some(suffix) = block_tensor_suffix(name_bytes, block_index) else {
                continue;
            };
            let wanted = matches!(
                suffix,
                b"attn_k.weight"
                    | b"attn_k_norm.weight"
                    | b"attn_norm.weight"
                    | b"attn_output.weight"
                    | b"attn_q.weight"
                    | b"attn_q_norm.weight"
                    | b"attn_v.weight"
                    | b"ffn_down.weight"
                    | b"ffn_gate.weight"
                    | b"ffn_norm.weight"
                    | b"ffn_up.weight"
            );
            if !wanted {
                continue;
            }
            let mut elements = 1u64;
            for dimension in &dimensions[..dimension_count as usize] {
                elements = elements.checked_mul(*dimension).ok_or(Error::Bounds)?;
            }
            let byte_len =
                u64::try_from(tensor_bytes(ggml_type, elements)?).map_err(|_| Error::Bounds)?;
            let absolute_offset = self
                .header
                .data_offset
                .checked_add(relative_offset)
                .ok_or(Error::Bounds)?;
            if absolute_offset.checked_add(byte_len).ok_or(Error::Bounds)? > self.header.source_len
            {
                return Err(Error::Truncated);
            }
            let descriptor = TensorDescriptor {
                dimensions,
                dimension_count,
                ggml_type,
                relative_offset,
                absolute_offset,
                byte_len,
            };
            match suffix {
                b"attn_k.weight" => attn_k = Some(descriptor),
                b"attn_k_norm.weight" => attn_k_norm = Some(descriptor),
                b"attn_norm.weight" => attn_norm = Some(descriptor),
                b"attn_output.weight" => attn_output = Some(descriptor),
                b"attn_q.weight" => attn_q = Some(descriptor),
                b"attn_q_norm.weight" => attn_q_norm = Some(descriptor),
                b"attn_v.weight" => attn_v = Some(descriptor),
                b"ffn_down.weight" => ffn_down = Some(descriptor),
                b"ffn_gate.weight" => ffn_gate = Some(descriptor),
                b"ffn_norm.weight" => ffn_norm = Some(descriptor),
                b"ffn_up.weight" => ffn_up = Some(descriptor),
                _ => {}
            }
        }
        Ok(QwenBlock0Tensors {
            attn_k: attn_k.ok_or(Error::Missing)?,
            attn_k_norm: attn_k_norm.ok_or(Error::Missing)?,
            attn_norm: attn_norm.ok_or(Error::Missing)?,
            attn_output: attn_output.ok_or(Error::Missing)?,
            attn_q: attn_q.ok_or(Error::Missing)?,
            attn_q_norm: attn_q_norm.ok_or(Error::Missing)?,
            attn_v: attn_v.ok_or(Error::Missing)?,
            ffn_down: ffn_down.ok_or(Error::Missing)?,
            ffn_gate: ffn_gate.ok_or(Error::Missing)?,
            ffn_norm: ffn_norm.ok_or(Error::Missing)?,
            ffn_up: ffn_up.ok_or(Error::Missing)?,
            descriptors_scanned: scanned,
        })
    }

    pub fn tokenizer<R: ReadAt>(&self, source: &mut R) -> Result<PagedTokenizer, Error> {
        let mut cursor = PagedCursor::at(source, 24)?;
        let mut model_gpt2 = false;
        let mut pre_qwen2 = false;
        let mut tokens = None;
        let mut merges = None;
        let mut token_types = None;
        let mut chat_template = None;
        let mut bos_token_id = None;
        let mut eos_token_id = None;
        let mut padding_token_id = None;
        let mut add_bos_token = None;

        for _ in 0..self.header.metadata_count {
            let key = cursor.take_small_name()?;
            let value_type = cursor.take_u32()?;
            match key.as_bytes() {
                Some(b"tokenizer.ggml.model") => {
                    if value_type != TYPE_STRING {
                        return Err(Error::Mismatch);
                    }
                    model_gpt2 = cursor.take_small_name()?.as_bytes() == Some(b"gpt2");
                }
                Some(b"tokenizer.ggml.pre") => {
                    if value_type != TYPE_STRING {
                        return Err(Error::Mismatch);
                    }
                    pre_qwen2 = cursor.take_small_name()?.as_bytes() == Some(b"qwen2");
                }
                Some(b"tokenizer.ggml.tokens") => {
                    tokens = Some(cursor.take_string_array(value_type)?);
                }
                Some(b"tokenizer.ggml.merges") => {
                    merges = Some(cursor.take_string_array(value_type)?);
                }
                Some(b"tokenizer.ggml.token_type") => {
                    token_types = Some(cursor.take_numeric_array(value_type, TYPE_I32)?);
                }
                Some(b"tokenizer.chat_template") => {
                    if value_type != TYPE_STRING {
                        return Err(Error::Mismatch);
                    }
                    let byte_len = cursor.take_u64()?;
                    if byte_len > MAX_CHAT_TEMPLATE_BYTES {
                        return Err(Error::Bounds);
                    }
                    let descriptor = TextDescriptor {
                        offset: cursor.offset,
                        byte_len,
                    };
                    cursor.advance(byte_len)?;
                    chat_template = Some(descriptor);
                }
                Some(b"tokenizer.ggml.bos_token_id") => {
                    bos_token_id = Some(take_paged_u32(&mut cursor, value_type)?);
                }
                Some(b"tokenizer.ggml.eos_token_id") => {
                    eos_token_id = Some(take_paged_u32(&mut cursor, value_type)?);
                }
                Some(b"tokenizer.ggml.padding_token_id") => {
                    padding_token_id = Some(take_paged_u32(&mut cursor, value_type)?);
                }
                Some(b"tokenizer.ggml.add_bos_token") => {
                    if value_type != TYPE_BOOL {
                        return Err(Error::Mismatch);
                    }
                    add_bos_token = Some(cursor.take_u8()? != 0);
                }
                _ => cursor.skip_value(value_type, 0)?,
            }
        }
        if !model_gpt2 || !pre_qwen2 {
            return Err(Error::Mismatch);
        }
        let tokenizer = PagedTokenizer {
            tokens: tokens.ok_or(Error::Missing)?,
            merges: merges.ok_or(Error::Missing)?,
            token_types: token_types.ok_or(Error::Missing)?,
            chat_template: chat_template.ok_or(Error::Missing)?,
            bos_token_id: bos_token_id.ok_or(Error::Missing)?,
            eos_token_id: eos_token_id.ok_or(Error::Missing)?,
            padding_token_id: padding_token_id.ok_or(Error::Missing)?,
            add_bos_token: add_bos_token.ok_or(Error::Missing)?,
        };
        if tokenizer.tokens.count == 0
            || tokenizer.tokens.count != tokenizer.token_types.count
            || tokenizer.merges.count == 0
            || u64::from(tokenizer.bos_token_id) >= tokenizer.tokens.count
            || u64::from(tokenizer.eos_token_id) >= tokenizer.tokens.count
            || u64::from(tokenizer.padding_token_id) >= tokenizer.tokens.count
        {
            return Err(Error::Mismatch);
        }
        Ok(tokenizer)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TensorDescriptor {
    pub dimensions: [u64; 4],
    pub dimension_count: u32,
    pub ggml_type: u32,
    pub relative_offset: u64,
    pub absolute_offset: u64,
    pub byte_len: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct QwenBlock0Tensors {
    pub attn_k: TensorDescriptor,
    pub attn_k_norm: TensorDescriptor,
    pub attn_norm: TensorDescriptor,
    pub attn_output: TensorDescriptor,
    pub attn_q: TensorDescriptor,
    pub attn_q_norm: TensorDescriptor,
    pub attn_v: TensorDescriptor,
    pub ffn_down: TensorDescriptor,
    pub ffn_gate: TensorDescriptor,
    pub ffn_norm: TensorDescriptor,
    pub ffn_up: TensorDescriptor,
    pub descriptors_scanned: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct StringArrayDescriptor {
    pub count: u64,
    pub payload_offset: u64,
    pub end_offset: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NumericArrayDescriptor {
    pub element_type: u32,
    pub count: u64,
    pub payload_offset: u64,
    pub end_offset: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TextDescriptor {
    pub offset: u64,
    pub byte_len: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PagedTokenizer {
    pub tokens: StringArrayDescriptor,
    pub merges: StringArrayDescriptor,
    pub token_types: NumericArrayDescriptor,
    pub chat_template: TextDescriptor,
    pub bos_token_id: u32,
    pub eos_token_id: u32,
    pub padding_token_id: u32,
    pub add_bos_token: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TokenizeReceipt {
    pub input_bytes: u32,
    pub pretokenized_pieces: u32,
    pub initial_symbols: u32,
    pub output_tokens: u32,
    pub merge_rules_scanned: u32,
    pub vocabulary_entries_scanned: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EmbeddingReceipt {
    pub token_id: u32,
    pub row_offset: u64,
    pub row_bytes: u32,
    pub decoded_values: u32,
}

const MAX_BASIC_INPUT_BYTES: usize = 96;
const MAX_BASIC_ENCODED_BYTES: usize = MAX_BASIC_INPUT_BYTES * 2;
const MAX_BASIC_SYMBOLS: usize = MAX_BASIC_INPUT_BYTES;
const MAX_TOKEN_TEXT_BYTES: usize = 256;
const MAX_CHAT_TEMPLATE_BYTES: u64 = 65_536;

const PAGED_NAME_BYTES: usize = 128;

#[derive(Clone, Copy)]
struct SmallName {
    bytes: [u8; PAGED_NAME_BYTES],
    length: usize,
    captured: bool,
}

impl SmallName {
    fn as_bytes(&self) -> Option<&[u8]> {
        self.captured.then_some(&self.bytes[..self.length])
    }
}

fn block_tensor_suffix(name: &[u8], wanted_block: u32) -> Option<&[u8]> {
    let prefix = b"blk.";
    if !name.starts_with(prefix) {
        return None;
    }
    let mut cursor = prefix.len();
    let mut block = 0u32;
    let mut digits = 0usize;
    while cursor < name.len() && name[cursor].is_ascii_digit() {
        block = block
            .checked_mul(10)?
            .checked_add(u32::from(name[cursor] - b'0'))?;
        cursor += 1;
        digits += 1;
    }
    if digits == 0 || name.get(cursor) != Some(&b'.') || block != wanted_block {
        return None;
    }
    name.get(cursor + 1..)
}

struct PagedCursor<'a, R: ReadAt> {
    source: &'a mut R,
    offset: u64,
}

impl<'a, R: ReadAt> PagedCursor<'a, R> {
    fn new(source: &'a mut R) -> Self {
        Self { source, offset: 0 }
    }

    fn at(source: &'a mut R, offset: u64) -> Result<Self, Error> {
        if offset > source.len() {
            return Err(Error::Truncated);
        }
        Ok(Self { source, offset })
    }

    fn read_exact(&mut self, output: &mut [u8]) -> Result<(), Error> {
        let length = u64::try_from(output.len()).map_err(|_| Error::Bounds)?;
        let end = self.offset.checked_add(length).ok_or(Error::Bounds)?;
        if end > self.source.len() {
            return Err(Error::Truncated);
        }
        self.source.read_exact_at(self.offset, output)?;
        self.offset = end;
        Ok(())
    }

    fn advance(&mut self, length: u64) -> Result<(), Error> {
        let end = self.offset.checked_add(length).ok_or(Error::Bounds)?;
        if end > self.source.len() {
            return Err(Error::Truncated);
        }
        self.offset = end;
        Ok(())
    }

    fn take_u32(&mut self) -> Result<u32, Error> {
        let mut bytes = [0u8; 4];
        self.read_exact(&mut bytes)?;
        Ok(u32::from_le_bytes(bytes))
    }

    fn take_u8(&mut self) -> Result<u8, Error> {
        let mut byte = [0u8; 1];
        self.read_exact(&mut byte)?;
        Ok(byte[0])
    }

    fn take_u64(&mut self) -> Result<u64, Error> {
        let mut bytes = [0u8; 8];
        self.read_exact(&mut bytes)?;
        Ok(u64::from_le_bytes(bytes))
    }

    fn take_small_name(&mut self) -> Result<SmallName, Error> {
        let length = self.take_u64()?;
        if length > MAX_NAME_BYTES {
            return Err(Error::Bounds);
        }
        let length_usize = usize::try_from(length).map_err(|_| Error::Bounds)?;
        let mut name = SmallName {
            bytes: [0u8; PAGED_NAME_BYTES],
            length: length_usize.min(PAGED_NAME_BYTES),
            captured: length_usize <= PAGED_NAME_BYTES,
        };
        if name.captured {
            self.read_exact(&mut name.bytes[..length_usize])?;
        } else {
            self.advance(length)?;
        }
        Ok(name)
    }

    fn skip_name(&mut self) -> Result<(), Error> {
        let length = self.take_u64()?;
        if length > MAX_NAME_BYTES {
            return Err(Error::Bounds);
        }
        self.advance(length)
    }

    fn take_string_array(&mut self, value_type: u32) -> Result<StringArrayDescriptor, Error> {
        if value_type != TYPE_ARRAY || self.take_u32()? != TYPE_STRING {
            return Err(Error::Mismatch);
        }
        let count = self.take_u64()?;
        if count == 0 || count > MAX_ARRAY_ITEMS {
            return Err(Error::Count);
        }
        let payload_offset = self.offset;
        for _ in 0..count {
            self.skip_value(TYPE_STRING, 1)?;
        }
        Ok(StringArrayDescriptor {
            count,
            payload_offset,
            end_offset: self.offset,
        })
    }

    fn take_numeric_array(
        &mut self,
        value_type: u32,
        expected_element_type: u32,
    ) -> Result<NumericArrayDescriptor, Error> {
        if value_type != TYPE_ARRAY {
            return Err(Error::Mismatch);
        }
        let element_type = self.take_u32()?;
        if element_type != expected_element_type {
            return Err(Error::Mismatch);
        }
        let count = self.take_u64()?;
        if count == 0 || count > MAX_ARRAY_ITEMS {
            return Err(Error::Count);
        }
        let width = match element_type {
            TYPE_U8 | TYPE_I8 | TYPE_BOOL => 1u64,
            TYPE_U16 | TYPE_I16 => 2,
            TYPE_U32 | TYPE_I32 | TYPE_F32 => 4,
            TYPE_U64 | TYPE_I64 | TYPE_F64 => 8,
            _ => return Err(Error::Type),
        };
        let payload_offset = self.offset;
        self.advance(count.checked_mul(width).ok_or(Error::Bounds)?)?;
        Ok(NumericArrayDescriptor {
            element_type,
            count,
            payload_offset,
            end_offset: self.offset,
        })
    }

    fn take_bounded_string(&mut self, output: &mut [u8]) -> Result<Option<usize>, Error> {
        let length = self.take_u64()?;
        let length_usize = usize::try_from(length).map_err(|_| Error::Bounds)?;
        if length_usize > output.len() {
            self.advance(length)?;
            return Ok(None);
        }
        self.read_exact(&mut output[..length_usize])?;
        Ok(Some(length_usize))
    }

    fn skip_value(&mut self, value_type: u32, depth: u8) -> Result<(), Error> {
        let fixed_width = match value_type {
            TYPE_U8 | TYPE_I8 | TYPE_BOOL => Some(1u64),
            TYPE_U16 | TYPE_I16 => Some(2),
            TYPE_U32 | TYPE_I32 | TYPE_F32 => Some(4),
            TYPE_U64 | TYPE_I64 | TYPE_F64 => Some(8),
            TYPE_STRING => {
                let length = self.take_u64()?;
                self.advance(length)?;
                return Ok(());
            }
            TYPE_ARRAY if depth < MAX_NESTING => None,
            _ => return Err(Error::Type),
        };
        if let Some(width) = fixed_width {
            return self.advance(width);
        }
        let element_type = self.take_u32()?;
        let count = self.take_u64()?;
        if count > MAX_ARRAY_ITEMS {
            return Err(Error::Count);
        }
        let element_width = match element_type {
            TYPE_U8 | TYPE_I8 | TYPE_BOOL => Some(1u64),
            TYPE_U16 | TYPE_I16 => Some(2),
            TYPE_U32 | TYPE_I32 | TYPE_F32 => Some(4),
            TYPE_U64 | TYPE_I64 | TYPE_F64 => Some(8),
            _ => None,
        };
        if let Some(width) = element_width {
            return self.advance(count.checked_mul(width).ok_or(Error::Bounds)?);
        }
        for _ in 0..count {
            self.skip_value(element_type, depth + 1)?;
        }
        Ok(())
    }
}

#[derive(Clone, Copy)]
struct TokenSpan {
    start: u16,
    end: u16,
    piece: u8,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum BasicClass {
    Letter,
    Digit,
    Space,
    Punctuation,
}

impl PagedTokenizer {
    /// Bounded Qwen2/GPT-2 byte-BPE path for ordinary ASCII and Latin text.
    ///
    /// The current gate deliberately rejects special-token syntax, control
    /// whitespace, contractions and non-Latin scripts. It is therefore a
    /// causal tokenizer slice, not a claim of complete chat-template support.
    pub fn tokenize_basic<R: ReadAt>(
        &self,
        source: &mut R,
        input: &[u8],
        output: &mut [u32],
    ) -> Result<TokenizeReceipt, Error> {
        if self.add_bos_token || input.len() > MAX_BASIC_INPUT_BYTES {
            return Err(Error::Unsupported);
        }
        if input.windows(2).any(|pair| pair == b"<|" || pair == b"|>") {
            return Err(Error::Unsupported);
        }
        if input.is_empty() {
            return Ok(TokenizeReceipt {
                input_bytes: 0,
                pretokenized_pieces: 0,
                initial_symbols: 0,
                output_tokens: 0,
                merge_rules_scanned: 0,
                vocabulary_entries_scanned: 0,
            });
        }

        let mut encoded = [0u8; MAX_BASIC_ENCODED_BYTES];
        let mut spans = [TokenSpan {
            start: 0,
            end: 0,
            piece: 0,
        }; MAX_BASIC_SYMBOLS];
        let mut encoded_len = 0usize;
        let mut symbol_count = 0usize;
        let mut input_offset = 0usize;
        let mut piece_count = 0usize;
        while input_offset < input.len() {
            let piece_end = next_basic_piece(input, input_offset)?;
            if piece_count >= u8::MAX as usize || piece_end <= input_offset {
                return Err(Error::Bounds);
            }
            for byte in &input[input_offset..piece_end] {
                if symbol_count >= spans.len() {
                    return Err(Error::Bounds);
                }
                let start = encoded_len;
                encode_gpt2_byte(*byte, &mut encoded, &mut encoded_len)?;
                spans[symbol_count] = TokenSpan {
                    start: u16::try_from(start).map_err(|_| Error::Bounds)?,
                    end: u16::try_from(encoded_len).map_err(|_| Error::Bounds)?,
                    piece: u8::try_from(piece_count).map_err(|_| Error::Bounds)?,
                };
                symbol_count += 1;
            }
            piece_count += 1;
            input_offset = piece_end;
        }
        let initial_symbols = symbol_count;

        let mut merge_cursor = PagedCursor::at(source, self.merges.payload_offset)?;
        let mut merge_text = [0u8; MAX_TOKEN_TEXT_BYTES];
        let mut merge_rules_scanned = 0u32;
        for _ in 0..self.merges.count {
            let captured = merge_cursor.take_bounded_string(&mut merge_text)?;
            merge_rules_scanned = merge_rules_scanned.checked_add(1).ok_or(Error::Bounds)?;
            let Some(length) = captured else {
                continue;
            };
            let Some(separator) = merge_text[..length].iter().position(|byte| *byte == b' ') else {
                return Err(Error::Mismatch);
            };
            if separator == 0 || separator + 1 >= length {
                return Err(Error::Mismatch);
            }
            merge_matching_pair(
                &encoded[..encoded_len],
                &mut spans,
                &mut symbol_count,
                &merge_text[..separator],
                &merge_text[separator + 1..length],
            );
        }
        if merge_cursor.offset != self.merges.end_offset || output.len() < symbol_count {
            return Err(Error::Bounds);
        }

        let mut token_ids = [u32::MAX; MAX_BASIC_SYMBOLS];
        let mut unresolved = symbol_count;
        let mut vocabulary_cursor = PagedCursor::at(source, self.tokens.payload_offset)?;
        let mut token_text = [0u8; MAX_TOKEN_TEXT_BYTES];
        let mut vocabulary_entries_scanned = 0u32;
        for token_id in 0..self.tokens.count {
            let captured = vocabulary_cursor.take_bounded_string(&mut token_text)?;
            vocabulary_entries_scanned = vocabulary_entries_scanned
                .checked_add(1)
                .ok_or(Error::Bounds)?;
            if let Some(length) = captured {
                for index in 0..symbol_count {
                    if token_ids[index] != u32::MAX {
                        continue;
                    }
                    let span = spans[index];
                    let start = usize::from(span.start);
                    let end = usize::from(span.end);
                    if encoded[start..end] == token_text[..length] {
                        token_ids[index] = u32::try_from(token_id).map_err(|_| Error::Bounds)?;
                        unresolved -= 1;
                    }
                }
            }
            if unresolved == 0 {
                break;
            }
        }
        if unresolved != 0 {
            return Err(Error::Missing);
        }
        output[..symbol_count].copy_from_slice(&token_ids[..symbol_count]);
        Ok(TokenizeReceipt {
            input_bytes: u32::try_from(input.len()).map_err(|_| Error::Bounds)?,
            pretokenized_pieces: u32::try_from(piece_count).map_err(|_| Error::Bounds)?,
            initial_symbols: u32::try_from(initial_symbols).map_err(|_| Error::Bounds)?,
            output_tokens: u32::try_from(symbol_count).map_err(|_| Error::Bounds)?,
            merge_rules_scanned,
            vocabulary_entries_scanned,
        })
    }

    pub fn token_text<R: ReadAt>(
        &self,
        source: &mut R,
        token_id: u32,
        output: &mut [u8],
    ) -> Result<usize, Error> {
        if u64::from(token_id) >= self.tokens.count {
            return Err(Error::Bounds);
        }
        let mut cursor = PagedCursor::at(source, self.tokens.payload_offset)?;
        for current in 0..=token_id {
            let value = cursor.take_bounded_string(output)?;
            if current == token_id {
                return value.ok_or(Error::Bounds);
            }
        }
        Err(Error::Missing)
    }
}

pub fn read_q6_k_embedding_row<R: ReadAt>(
    source: &mut R,
    tensor: TensorDescriptor,
    token_id: u32,
    output: &mut [f32],
) -> Result<EmbeddingReceipt, Error> {
    if tensor.ggml_type != GGML_TYPE_Q6_K
        || tensor.dimension_count != 2
        || tensor.dimensions[0] == 0
        || tensor.dimensions[0] % QK_K as u64 != 0
        || output.len() != usize::try_from(tensor.dimensions[0]).map_err(|_| Error::Bounds)?
        || u64::from(token_id) >= tensor.dimensions[1]
    {
        return Err(Error::Mismatch);
    }
    let blocks_per_row = tensor.dimensions[0] / QK_K as u64;
    let row_bytes = blocks_per_row
        .checked_mul(Q6_K_BLOCK_BYTES as u64)
        .ok_or(Error::Bounds)?;
    let row_offset = tensor
        .absolute_offset
        .checked_add(
            u64::from(token_id)
                .checked_mul(row_bytes)
                .ok_or(Error::Bounds)?,
        )
        .ok_or(Error::Bounds)?;
    let row_end = row_offset.checked_add(row_bytes).ok_or(Error::Bounds)?;
    let tensor_end = tensor
        .absolute_offset
        .checked_add(tensor.byte_len)
        .ok_or(Error::Bounds)?;
    if row_end > tensor_end || row_end > source.len() {
        return Err(Error::Truncated);
    }
    let mut raw = [0u8; Q6_K_BLOCK_BYTES];
    let mut decoded = [0.0f32; QK_K];
    for block_index in 0..blocks_per_row {
        source.read_exact_at(row_offset + block_index * Q6_K_BLOCK_BYTES as u64, &mut raw)?;
        dequantize_q6_k_block(&raw, &mut decoded)?;
        let output_start = usize::try_from(block_index)
            .map_err(|_| Error::Bounds)?
            .checked_mul(QK_K)
            .ok_or(Error::Bounds)?;
        output[output_start..output_start + QK_K].copy_from_slice(&decoded);
    }
    Ok(EmbeddingReceipt {
        token_id,
        row_offset,
        row_bytes: u32::try_from(row_bytes).map_err(|_| Error::Bounds)?,
        decoded_values: u32::try_from(output.len()).map_err(|_| Error::Bounds)?,
    })
}

fn merge_matching_pair(
    encoded: &[u8],
    spans: &mut [TokenSpan; MAX_BASIC_SYMBOLS],
    symbol_count: &mut usize,
    left: &[u8],
    right: &[u8],
) {
    let mut index = 0usize;
    while index + 1 < *symbol_count {
        let a = spans[index];
        let b = spans[index + 1];
        let a_bytes = &encoded[usize::from(a.start)..usize::from(a.end)];
        let b_bytes = &encoded[usize::from(b.start)..usize::from(b.end)];
        if a.piece == b.piece && a_bytes == left && b_bytes == right {
            spans[index].end = b.end;
            for shift in index + 1..*symbol_count - 1 {
                spans[shift] = spans[shift + 1];
            }
            *symbol_count -= 1;
            index += 1;
        } else {
            index += 1;
        }
    }
}

fn next_basic_piece(input: &[u8], offset: usize) -> Result<usize, Error> {
    let (codepoint, width) = decode_utf8(input, offset)?;
    let class = basic_class(codepoint)?;
    match class {
        BasicClass::Letter => consume_class(input, offset + width, BasicClass::Letter),
        BasicClass::Digit => {
            let mut end = offset + width;
            for _ in 1..3 {
                if end >= input.len() {
                    break;
                }
                let (next, next_width) = decode_utf8(input, end)?;
                if basic_class(next)? != BasicClass::Digit {
                    break;
                }
                end += next_width;
            }
            Ok(end)
        }
        BasicClass::Space => {
            let after_space = offset + width;
            if after_space >= input.len() {
                return Ok(after_space);
            }
            let (next, next_width) = decode_utf8(input, after_space)?;
            if basic_class(next)? == BasicClass::Letter {
                consume_class(input, after_space + next_width, BasicClass::Letter)
            } else {
                Ok(after_space)
            }
        }
        BasicClass::Punctuation => consume_class(input, offset + width, BasicClass::Punctuation),
    }
}

fn consume_class(input: &[u8], mut offset: usize, wanted: BasicClass) -> Result<usize, Error> {
    while offset < input.len() {
        let (codepoint, width) = decode_utf8(input, offset)?;
        if basic_class(codepoint)? != wanted {
            break;
        }
        offset += width;
    }
    Ok(offset)
}

fn basic_class(codepoint: u32) -> Result<BasicClass, Error> {
    match codepoint {
        0x61..=0x7a | 0x41..=0x5a | 0x00c0..=0x024f => Ok(BasicClass::Letter),
        0x30..=0x39 => Ok(BasicClass::Digit),
        0x20 => Ok(BasicClass::Space),
        0x21..=0x2f | 0x3a..=0x40 | 0x5b..=0x60 | 0x7b..=0x7e if codepoint != 0x27 => {
            Ok(BasicClass::Punctuation)
        }
        _ => Err(Error::Unsupported),
    }
}

fn decode_utf8(input: &[u8], offset: usize) -> Result<(u32, usize), Error> {
    let first = *input.get(offset).ok_or(Error::Truncated)?;
    if first < 0x80 {
        return Ok((u32::from(first), 1));
    }
    let (width, mut codepoint, minimum) = match first {
        0xc2..=0xdf => (2usize, u32::from(first & 0x1f), 0x80),
        0xe0..=0xef => (3, u32::from(first & 0x0f), 0x800),
        0xf0..=0xf4 => (4, u32::from(first & 0x07), 0x10000),
        _ => return Err(Error::Utf8),
    };
    let end = offset.checked_add(width).ok_or(Error::Bounds)?;
    let bytes = input.get(offset + 1..end).ok_or(Error::Utf8)?;
    for byte in bytes {
        if byte & 0xc0 != 0x80 {
            return Err(Error::Utf8);
        }
        codepoint = (codepoint << 6) | u32::from(byte & 0x3f);
    }
    if codepoint < minimum || codepoint > 0x10ffff || (0xd800..=0xdfff).contains(&codepoint) {
        return Err(Error::Utf8);
    }
    Ok((codepoint, width))
}

fn encode_gpt2_byte(
    byte: u8,
    output: &mut [u8; MAX_BASIC_ENCODED_BYTES],
    length: &mut usize,
) -> Result<(), Error> {
    let codepoint = match byte {
        33..=126 | 161..=172 | 174..=255 => u16::from(byte),
        0..=32 => 256 + u16::from(byte),
        127..=160 => 256 + 33 + u16::from(byte - 127),
        173 => 323,
    };
    if codepoint < 0x80 {
        if *length >= output.len() {
            return Err(Error::Bounds);
        }
        output[*length] = codepoint as u8;
        *length += 1;
    } else {
        if *length + 2 > output.len() {
            return Err(Error::Bounds);
        }
        output[*length] = 0xc0 | ((codepoint >> 6) as u8);
        output[*length + 1] = 0x80 | ((codepoint & 0x3f) as u8);
        *length += 2;
    }
    Ok(())
}

fn take_paged_u32<R: ReadAt>(
    cursor: &mut PagedCursor<'_, R>,
    value_type: u32,
) -> Result<u32, Error> {
    if value_type != TYPE_U32 {
        return Err(Error::Mismatch);
    }
    cursor.take_u32()
}

fn take_paged_f32<R: ReadAt>(
    cursor: &mut PagedCursor<'_, R>,
    value_type: u32,
) -> Result<f32, Error> {
    if value_type != TYPE_F32 {
        return Err(Error::Mismatch);
    }
    let value = f32::from_bits(cursor.take_u32()?);
    value.is_finite().then_some(value).ok_or(Error::NonFinite)
}

fn validate_qwen_config(config: QwenConfig) -> Result<(), Error> {
    if config.context_length == 0
        || config.embedding_length == 0
        || config.feed_forward_length == 0
        || config.block_count == 0
        || config.head_count == 0
        || config.head_count_kv == 0
        || !config.rope_frequency_base.is_finite()
        || !config.rms_epsilon.is_finite()
        || config.rms_epsilon <= 0.0
    {
        return Err(Error::Mismatch);
    }
    Ok(())
}

fn align_up_u64(value: u64, alignment: u64) -> Result<u64, Error> {
    let mask = alignment.checked_sub(1).ok_or(Error::Alignment)?;
    value
        .checked_add(mask)
        .map(|sum| sum & !mask)
        .ok_or(Error::Bounds)
}

pub fn tensor_bytes(ggml_type: u32, elements: u64) -> Result<usize, Error> {
    match ggml_type {
        0 => usize::try_from(elements.checked_mul(4).ok_or(Error::Bounds)?)
            .map_err(|_| Error::Bounds),
        1 => usize::try_from(elements.checked_mul(2).ok_or(Error::Bounds)?)
            .map_err(|_| Error::Bounds),
        GGML_TYPE_Q4_K => {
            if !elements.is_multiple_of(QK_K as u64) {
                return Err(Error::Quantization);
            }
            usize::try_from(
                (elements / QK_K as u64)
                    .checked_mul(Q4_K_BLOCK_BYTES as u64)
                    .ok_or(Error::Bounds)?,
            )
            .map_err(|_| Error::Bounds)
        }
        GGML_TYPE_Q6_K => {
            if !elements.is_multiple_of(QK_K as u64) {
                return Err(Error::Quantization);
            }
            usize::try_from(
                (elements / QK_K as u64)
                    .checked_mul(Q6_K_BLOCK_BYTES as u64)
                    .ok_or(Error::Bounds)?,
            )
            .map_err(|_| Error::Bounds)
        }
        _ => Err(Error::Quantization),
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct MatVecReceipt {
    pub rows: u32,
    pub input_values: u32,
    pub quantized_blocks: u64,
    pub weight_bytes_read: u64,
    pub multiply_accumulates: u64,
}

/// Read a complete F32 vector after the descriptor has been admitted by the
/// GGUF parser. The caller owns the activation buffer; model bytes never enter
/// an unbounded allocation in this crate.
pub fn read_f32_vector<R: ReadAt>(
    source: &mut R,
    tensor: TensorDescriptor,
    output: &mut [f32],
) -> Result<(), Error> {
    if tensor.dimension_count != 1
        || tensor.ggml_type != 0
        || tensor.dimensions[0] != output.len() as u64
        || tensor.byte_len != output.len() as u64 * 4
    {
        return Err(Error::Mismatch);
    }
    let mut bytes = [0u8; 4];
    for (index, value) in output.iter_mut().enumerate() {
        let offset = tensor
            .absolute_offset
            .checked_add((index as u64).checked_mul(4).ok_or(Error::Bounds)?)
            .ok_or(Error::Bounds)?;
        source.read_exact_at(offset, &mut bytes)?;
        *value = f32::from_bits(u32::from_le_bytes(bytes));
        if !value.is_finite() {
            return Err(Error::NonFinite);
        }
    }
    Ok(())
}

/// Matrix-vector multiplication for row-major GGML Q4_K/Q6_K matrices.
/// `dimensions[0]` is the input width and `dimensions[1]` the output width.
pub fn quantized_matvec<R: ReadAt>(
    source: &mut R,
    tensor: TensorDescriptor,
    input: &[f32],
    output: &mut [f32],
) -> Result<MatVecReceipt, Error> {
    if tensor.dimension_count != 2
        || tensor.dimensions[0] != input.len() as u64
        || tensor.dimensions[1] != output.len() as u64
        || !input.len().is_multiple_of(QK_K)
        || input.iter().any(|value| !value.is_finite())
    {
        return Err(Error::Mismatch);
    }
    let block_bytes = match tensor.ggml_type {
        GGML_TYPE_Q4_K => Q4_K_BLOCK_BYTES,
        GGML_TYPE_Q6_K => Q6_K_BLOCK_BYTES,
        _ => return Err(Error::Quantization),
    };
    let blocks_per_row = input.len() / QK_K;
    let expected_bytes = output
        .len()
        .checked_mul(blocks_per_row)
        .and_then(|blocks| blocks.checked_mul(block_bytes))
        .ok_or(Error::Bounds)?;
    if tensor.byte_len != expected_bytes as u64 {
        return Err(Error::Mismatch);
    }
    let mut q4 = [0u8; Q4_K_BLOCK_BYTES];
    let mut q6 = [0u8; Q6_K_BLOCK_BYTES];
    for (row, result) in output.iter_mut().enumerate() {
        let mut sum = 0.0f32;
        for block_index in 0..blocks_per_row {
            let first = block_index * QK_K;
            let chunk = &input[first..first + QK_K];
            let linear_block = row
                .checked_mul(blocks_per_row)
                .and_then(|value| value.checked_add(block_index))
                .ok_or(Error::Bounds)?;
            let offset = tensor
                .absolute_offset
                .checked_add(
                    (linear_block as u64)
                        .checked_mul(block_bytes as u64)
                        .ok_or(Error::Bounds)?,
                )
                .ok_or(Error::Bounds)?;
            let dot = match tensor.ggml_type {
                GGML_TYPE_Q4_K => {
                    source.read_exact_at(offset, &mut q4)?;
                    dot_q4_k_block(&q4, chunk)?
                }
                GGML_TYPE_Q6_K => {
                    source.read_exact_at(offset, &mut q6)?;
                    dot_q6_k_block(&q6, chunk)?
                }
                _ => return Err(Error::Quantization),
            };
            sum += dot;
        }
        if !sum.is_finite() {
            return Err(Error::NonFinite);
        }
        *result = sum;
    }
    let quantized_blocks = (output.len() as u64)
        .checked_mul(blocks_per_row as u64)
        .ok_or(Error::Bounds)?;
    Ok(MatVecReceipt {
        rows: u32::try_from(output.len()).map_err(|_| Error::Bounds)?,
        input_values: u32::try_from(input.len()).map_err(|_| Error::Bounds)?,
        quantized_blocks,
        weight_bytes_read: quantized_blocks
            .checked_mul(block_bytes as u64)
            .ok_or(Error::Bounds)?,
        multiply_accumulates: (output.len() as u64)
            .checked_mul(input.len() as u64)
            .ok_or(Error::Bounds)?,
    })
}

/// Quantize an activation row exactly as ggml's reference Q8_K path and
/// immediately dequantize it into caller-owned scratch.  Keeping the scratch
/// as `f32` lets the existing, independently tested Q4_K/Q6_K readers remain
/// the weight primitive while restoring the activation precision actually
/// consumed by llama.cpp.  The observable arithmetic is therefore Q8_K
/// bounded even though this scalar implementation does not use the packed
/// integer SIMD representation.
pub fn quantize_q8_k_dequantized(input: &[f32], output: &mut [f32]) -> Result<(), Error> {
    if input.is_empty()
        || !input.len().is_multiple_of(QK_K)
        || output.len() < input.len()
        || input.iter().any(|value| !value.is_finite())
    {
        return Err(Error::Mismatch);
    }
    for (source, target) in input.chunks_exact(QK_K).zip(output.chunks_exact_mut(QK_K)) {
        let mut maximum = 0.0f32;
        let mut absolute_maximum = 0.0f32;
        for value in source {
            let absolute = value.abs();
            if absolute > absolute_maximum {
                absolute_maximum = absolute;
                maximum = *value;
            }
        }
        if absolute_maximum == 0.0 {
            target.fill(0.0);
            continue;
        }
        // Source of truth: ggml quantize_row_q8_K_ref. The signed maximum
        // makes the largest-magnitude element map to -127 and bounds every
        // other rounded value to the representable interval.
        let inverse_scale = -127.0f32 / maximum;
        let scale = 1.0f32 / inverse_scale;
        for (value, quantized) in source.iter().zip(target.iter_mut()) {
            let integer = nearest_int_ggml(inverse_scale * *value)?.min(127);
            if !(-127..=127).contains(&integer) {
                return Err(Error::Quantization);
            }
            *quantized = scale * integer as f32;
        }
    }
    Ok(())
}

/// Matrix-vector product using the Q8_K activation contract used by ggml for
/// Q4_K and Q6_K weights. `scratch` must be at least as wide as `input`.
pub fn quantized_matvec_q8_k<R: ReadAt>(
    source: &mut R,
    tensor: TensorDescriptor,
    input: &[f32],
    output: &mut [f32],
    scratch: &mut [f32],
) -> Result<MatVecReceipt, Error> {
    if scratch.len() < input.len() {
        return Err(Error::Mismatch);
    }
    quantize_q8_k_dequantized(input, &mut scratch[..input.len()])?;
    quantized_matvec(source, tensor, &scratch[..input.len()], output)
}

/// Scalar, freestanding equivalent of ggml's packed Q4_K/Q6_K x Q8_K dot
/// path. Integer products are accumulated before applying block scales; this
/// ordering is required for stable agreement after many transformer blocks.
pub fn quantized_matvec_q8_k_packed<R: ReadAt>(
    source: &mut R,
    tensor: TensorDescriptor,
    input: &[f32],
    output: &mut [f32],
) -> Result<MatVecReceipt, Error> {
    if tensor.dimension_count != 2
        || tensor.dimensions[0] != input.len() as u64
        || tensor.dimensions[1] != output.len() as u64
        || input.is_empty()
        || input.len() > QWEN3_FFN_LENGTH
        || !input.len().is_multiple_of(QK_K)
        || input.iter().any(|value| !value.is_finite())
    {
        return Err(Error::Mismatch);
    }
    let block_bytes = match tensor.ggml_type {
        GGML_TYPE_Q4_K => Q4_K_BLOCK_BYTES,
        GGML_TYPE_Q6_K => Q6_K_BLOCK_BYTES,
        _ => return Err(Error::Quantization),
    };
    let blocks_per_row = input.len() / QK_K;
    let expected_bytes = output
        .len()
        .checked_mul(blocks_per_row)
        .and_then(|blocks| blocks.checked_mul(block_bytes))
        .ok_or(Error::Bounds)?;
    if tensor.byte_len != expected_bytes as u64 {
        return Err(Error::Mismatch);
    }

    let mut q8 = [0i8; QWEN3_FFN_LENGTH];
    let mut q8_scales = [0.0f32; QWEN3_FFN_LENGTH / QK_K];
    let mut q8_sums = [0i16; QWEN3_FFN_LENGTH / 16];
    for (block_index, values) in input.chunks_exact(QK_K).enumerate() {
        let mut maximum = 0.0f32;
        let mut absolute_maximum = 0.0f32;
        for value in values {
            let absolute = value.abs();
            if absolute > absolute_maximum {
                absolute_maximum = absolute;
                maximum = *value;
            }
        }
        if absolute_maximum == 0.0 {
            continue;
        }
        let inverse_scale = -127.0f32 / maximum;
        q8_scales[block_index] = 1.0f32 / inverse_scale;
        let q8_base = block_index * QK_K;
        let sum_base = block_index * (QK_K / 16);
        for index in 0..QK_K {
            let integer = nearest_int_ggml(inverse_scale * values[index])?.min(127);
            if !(-127..=127).contains(&integer) {
                return Err(Error::Quantization);
            }
            q8[q8_base + index] = integer as i8;
        }
        for group in 0..QK_K / 16 {
            let mut sum = 0i16;
            for value in &q8[q8_base + group * 16..q8_base + (group + 1) * 16] {
                sum = sum.checked_add(i16::from(*value)).ok_or(Error::Bounds)?;
            }
            q8_sums[sum_base + group] = sum;
        }
    }

    let mut q4 = [0u8; Q4_K_BLOCK_BYTES];
    let mut q6 = [0u8; Q6_K_BLOCK_BYTES];
    for (row, result) in output.iter_mut().enumerate() {
        let mut sum = 0.0f32;
        for block_index in 0..blocks_per_row {
            let linear_block = row
                .checked_mul(blocks_per_row)
                .and_then(|value| value.checked_add(block_index))
                .ok_or(Error::Bounds)?;
            let offset = tensor
                .absolute_offset
                .checked_add(
                    (linear_block as u64)
                        .checked_mul(block_bytes as u64)
                        .ok_or(Error::Bounds)?,
                )
                .ok_or(Error::Bounds)?;
            let input_base = block_index * QK_K;
            let input_scale = q8_scales[block_index];
            let block_sum = match tensor.ggml_type {
                GGML_TYPE_Q4_K => {
                    source.read_exact_at(offset, &mut q4)?;
                    dot_q4_k_q8_k_packed(
                        &q4,
                        &q8[input_base..input_base + QK_K],
                        &q8_sums[block_index * 16..block_index * 16 + 16],
                        input_scale,
                    )?
                }
                GGML_TYPE_Q6_K => {
                    source.read_exact_at(offset, &mut q6)?;
                    dot_q6_k_q8_k_packed(
                        &q6,
                        &q8[input_base..input_base + QK_K],
                        input_scale,
                    )?
                }
                _ => return Err(Error::Quantization),
            };
            sum += block_sum;
        }
        if !sum.is_finite() {
            return Err(Error::NonFinite);
        }
        *result = sum;
    }
    let quantized_blocks = (output.len() as u64)
        .checked_mul(blocks_per_row as u64)
        .ok_or(Error::Bounds)?;
    Ok(MatVecReceipt {
        rows: u32::try_from(output.len()).map_err(|_| Error::Bounds)?,
        input_values: u32::try_from(input.len()).map_err(|_| Error::Bounds)?,
        quantized_blocks,
        weight_bytes_read: quantized_blocks
            .checked_mul(block_bytes as u64)
            .ok_or(Error::Bounds)?,
        multiply_accumulates: (output.len() as u64)
            .checked_mul(input.len() as u64)
            .ok_or(Error::Bounds)?,
    })
}

pub fn rms_norm(
    input: &[f32],
    weight: &[f32],
    epsilon: f32,
    output: &mut [f32],
) -> Result<(), Error> {
    if input.is_empty()
        || input.len() != weight.len()
        || input.len() != output.len()
        || !epsilon.is_finite()
        || epsilon <= 0.0
        || input.iter().chain(weight).any(|value| !value.is_finite())
    {
        return Err(Error::Mismatch);
    }
    let mut mean_square = 0.0f32;
    for value in input {
        mean_square += *value * *value;
    }
    mean_square = mean_square / input.len() as f32 + epsilon;
    let inverse = 1.0 / sqrt_f32(mean_square)?;
    for index in 0..input.len() {
        output[index] = input[index] * inverse * weight[index];
        if !output[index].is_finite() {
            return Err(Error::NonFinite);
        }
    }
    Ok(())
}

pub fn rms_norm_heads_in_place(
    values: &mut [f32],
    weight: &[f32],
    head_count: usize,
    epsilon: f32,
) -> Result<(), Error> {
    if head_count == 0
        || weight.is_empty()
        || values.len() != head_count.checked_mul(weight.len()).ok_or(Error::Bounds)?
    {
        return Err(Error::Mismatch);
    }
    for head in values.chunks_exact_mut(weight.len()) {
        let mut mean_square = 0.0f32;
        for value in head.iter() {
            if !value.is_finite() {
                return Err(Error::NonFinite);
            }
            mean_square += *value * *value;
        }
        let inverse = 1.0 / sqrt_f32(mean_square / weight.len() as f32 + epsilon)?;
        for (value, scale) in head.iter_mut().zip(weight) {
            *value = *value * inverse * *scale;
            if !value.is_finite() {
                return Err(Error::NonFinite);
            }
        }
    }
    Ok(())
}

/// Bounded Qwen3/GGML NeoX-RoPE.
///
/// Qwen3 is explicitly classified as `LLAMA_ROPE_TYPE_NEOX` by llama.cpp.
/// Each element in the first half of a 128-value head rotates with the
/// corresponding element in the second half; adjacent-pair rotation is the
/// different `GGML_ROPE_TYPE_NORMAL` layout and is not valid for Qwen3. NP7
/// admits a deliberately small context and performs explicit range reduction
/// instead of depending on a platform libm.
pub fn rope_qwen3_in_place(
    values: &mut [f32],
    head_count: usize,
    position: u32,
    frequency_base: f32,
) -> Result<(), Error> {
    const ADOPTED_FREQUENCY_BASE: f32 = 1_000_000.0;
    const HEAD_DIMENSION: usize = 128;
    const MAX_POSITION: u32 = 127;
    // exp(-ln(1_000_000) / 64), frozen for the adopted Qwen3 ABI.
    const FREQUENCY_RATIO: f32 = 0.805_842_16;
    if values.len()
        != head_count
            .checked_mul(HEAD_DIMENSION)
            .ok_or(Error::Bounds)?
        || frequency_base.to_bits() != ADOPTED_FREQUENCY_BASE.to_bits()
        || position > MAX_POSITION
    {
        return Err(Error::Unsupported);
    }
    if position == 0 {
        return Ok(());
    }
    const HALF_HEAD: usize = HEAD_DIMENSION / 2;
    for head in values.chunks_exact_mut(HEAD_DIMENSION) {
        let mut theta = position as f32;
        for index in 0..HALF_HEAD {
            let (sine, cosine) = sin_cos_bounded(theta);
            let first = head[index];
            let second = head[index + HALF_HEAD];
            head[index] = first * cosine - second * sine;
            head[index + HALF_HEAD] = first * sine + second * cosine;
            if !head[index].is_finite() || !head[index + HALF_HEAD].is_finite() {
                return Err(Error::NonFinite);
            }
            theta *= FREQUENCY_RATIO;
        }
    }
    Ok(())
}

/// Compatibility surface for the already sealed NP6 gate.
pub fn rope_qwen3_np6_in_place(
    values: &mut [f32],
    head_count: usize,
    position: u32,
    frequency_base: f32,
) -> Result<(), Error> {
    if position > 1 {
        return Err(Error::Unsupported);
    }
    rope_qwen3_in_place(values, head_count, position, frequency_base)
}

// NP9 proved the incremental two-token path. NP10 keeps a deliberately small
// creation envelope while allowing a complete compact chat-template prompt and
// bounded answer. This remains far below the 40,960-token model metadata and
// must not be represented as full-context support.
pub const NP7_MAX_CONTEXT_TOKENS: usize = 128;

/// Causal grouped-query attention for the NP7 bounded context. Keys/values are
/// laid out `[context][kv_head][head_dimension]`.
pub fn grouped_query_attention_bounded(
    query: &[f32],
    keys: &[f32],
    values: &[f32],
    q_heads: usize,
    kv_heads: usize,
    head_dimension: usize,
    context: usize,
    output: &mut [f32],
    weights: &mut [f32],
) -> Result<(), Error> {
    if context == 0
        || context > NP7_MAX_CONTEXT_TOKENS
        || q_heads == 0
        || kv_heads == 0
        || !q_heads.is_multiple_of(kv_heads)
        || query.len() != q_heads.checked_mul(head_dimension).ok_or(Error::Bounds)?
        || keys.len()
            != context
                .checked_mul(kv_heads)
                .and_then(|value| value.checked_mul(head_dimension))
                .ok_or(Error::Bounds)?
        || values.len() != keys.len()
        || output.len() != query.len()
        || weights.len() != q_heads.checked_mul(context).ok_or(Error::Bounds)?
    {
        return Err(Error::Mismatch);
    }
    let inverse_sqrt = 1.0 / sqrt_f32(head_dimension as f32)?;
    let group_size = q_heads / kv_heads;
    for q_head in 0..q_heads {
        let kv_head = q_head / group_size;
        let q = &query[q_head * head_dimension..(q_head + 1) * head_dimension];
        let mut scores = [0.0f32; NP7_MAX_CONTEXT_TOKENS];
        let mut maximum = f32::NEG_INFINITY;
        for token in 0..context {
            let base = (token * kv_heads + kv_head) * head_dimension;
            let key = &keys[base..base + head_dimension];
            let mut score = 0.0f32;
            for dimension in 0..head_dimension {
                score += q[dimension] * key[dimension];
            }
            score *= inverse_sqrt;
            if !score.is_finite() {
                return Err(Error::NonFinite);
            }
            scores[token] = score;
            maximum = maximum.max(score);
        }
        let mut denominator = 0.0f32;
        for token in 0..context {
            scores[token] = exp_negative(scores[token] - maximum)?;
            denominator += scores[token];
        }
        if !denominator.is_finite() || denominator <= 0.0 {
            return Err(Error::NonFinite);
        }
        for token in 0..context {
            weights[q_head * context + token] = scores[token] / denominator;
        }
        let target = &mut output[q_head * head_dimension..(q_head + 1) * head_dimension];
        target.fill(0.0);
        for token in 0..context {
            let base = (token * kv_heads + kv_head) * head_dimension;
            let value = &values[base..base + head_dimension];
            let weight = weights[q_head * context + token];
            for dimension in 0..head_dimension {
                target[dimension] += weight * value[dimension];
            }
        }
    }
    if output.iter().all(|value| value.is_finite()) {
        Ok(())
    } else {
        Err(Error::NonFinite)
    }
}

/// Compatibility surface for NP6's frozen one/two-token contract.
pub fn grouped_query_attention_np6(
    query: &[f32],
    keys: &[f32],
    values: &[f32],
    q_heads: usize,
    kv_heads: usize,
    head_dimension: usize,
    context: usize,
    output: &mut [f32],
    weights: &mut [f32],
) -> Result<(), Error> {
    if context > NP6_CONTEXT_TOKENS {
        return Err(Error::Unsupported);
    }
    grouped_query_attention_bounded(
        query,
        keys,
        values,
        q_heads,
        kv_heads,
        head_dimension,
        context,
        output,
        weights,
    )
}

pub fn swiglu(gate: &[f32], up: &[f32], output: &mut [f32]) -> Result<(), Error> {
    if gate.len() != up.len() || gate.len() != output.len() {
        return Err(Error::Mismatch);
    }
    for index in 0..gate.len() {
        let value = gate[index];
        if !value.is_finite() || !up[index].is_finite() {
            return Err(Error::NonFinite);
        }
        let sigmoid = if value >= 0.0 {
            1.0 / (1.0 + exp_negative(-value)?)
        } else {
            let exponential = exp_negative(value)?;
            exponential / (1.0 + exponential)
        };
        output[index] = value * sigmoid * up[index];
        if !output[index].is_finite() {
            return Err(Error::NonFinite);
        }
    }
    Ok(())
}

pub const NP6_CONTEXT_TOKENS: usize = 2;
pub const QWEN3_EMBEDDING_LENGTH: usize = 2_560;
pub const QWEN3_Q_LENGTH: usize = 4_096;
pub const QWEN3_KV_LENGTH: usize = 1_024;
pub const QWEN3_FFN_LENGTH: usize = 9_728;
pub const QWEN3_Q_HEADS: usize = 32;
pub const QWEN3_KV_HEADS: usize = 8;
pub const QWEN3_HEAD_DIMENSION: usize = 128;

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct StageSummary {
    pub values: u32,
    pub sum_f64: f64,
    pub square_sum_f64: f64,
    pub minimum: f32,
    pub maximum: f32,
}

impl StageSummary {
    pub fn from_values(values: &[f32]) -> Result<Self, Error> {
        if values.is_empty() {
            return Err(Error::Mismatch);
        }
        let mut sum = 0.0f64;
        let mut square_sum = 0.0f64;
        let mut minimum = f32::INFINITY;
        let mut maximum = f32::NEG_INFINITY;
        for value in values {
            if !value.is_finite() {
                return Err(Error::NonFinite);
            }
            let wide = f64::from(*value);
            sum += wide;
            square_sum += wide * wide;
            minimum = minimum.min(*value);
            maximum = maximum.max(*value);
        }
        Ok(Self {
            values: u32::try_from(values.len()).map_err(|_| Error::Bounds)?,
            sum_f64: sum,
            square_sum_f64: square_sum,
            minimum,
            maximum,
        })
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct QwenBlockTokenReceipt {
    pub token_id: u32,
    pub position: u32,
    pub context: u32,
    pub embedding: StageSummary,
    pub attn_norm: StageSummary,
    pub query_projection: StageSummary,
    pub key_projection: StageSummary,
    pub value_projection: StageSummary,
    pub query_norm: StageSummary,
    pub key_norm: StageSummary,
    pub query_rope: StageSummary,
    pub key_rope: StageSummary,
    pub attention_weights: StageSummary,
    pub attention_context: StageSummary,
    pub attention_projection: StageSummary,
    pub attention_residual: StageSummary,
    pub ffn_norm: StageSummary,
    pub ffn_gate: StageSummary,
    pub ffn_up: StageSummary,
    pub ffn_activated: StageSummary,
    pub ffn_down: StageSummary,
    pub block_output: StageSummary,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct BlockWorkReceipt {
    pub matvec_calls: u32,
    pub quantized_blocks: u64,
    pub weight_bytes_read: u64,
    pub multiply_accumulates: u64,
}

/// Deterministic cancellation and ordering boundary for a decoder pass.
///
/// The caller must enter and complete each block in sequence. Cancellation is
/// checked before the next block starts, so a late result can never be
/// mistaken for a completed decoder receipt.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DecoderBlockWatchdog {
    required_blocks: u32,
    next_block: u32,
    cancelled: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WatchdogError {
    Bounds,
    Cancelled,
    OutOfOrder,
    Incomplete,
}

impl DecoderBlockWatchdog {
    pub const fn new(required_blocks: u32) -> Result<Self, WatchdogError> {
        if required_blocks == 0 {
            return Err(WatchdogError::Bounds);
        }
        Ok(Self {
            required_blocks,
            next_block: 0,
            cancelled: false,
        })
    }

    pub fn cancel(&mut self) {
        self.cancelled = true;
    }

    pub const fn begin_block(&self, block_index: u32) -> Result<(), WatchdogError> {
        if self.cancelled {
            return Err(WatchdogError::Cancelled);
        }
        if block_index != self.next_block || block_index >= self.required_blocks {
            return Err(WatchdogError::OutOfOrder);
        }
        Ok(())
    }

    pub fn complete_block(&mut self, block_index: u32) -> Result<(), WatchdogError> {
        self.begin_block(block_index)?;
        self.next_block = self
            .next_block
            .checked_add(1)
            .ok_or(WatchdogError::Bounds)?;
        Ok(())
    }

    pub const fn completed_blocks(&self) -> u32 {
        self.next_block
    }

    pub const fn finish(&self) -> Result<(), WatchdogError> {
        if self.cancelled {
            return Err(WatchdogError::Cancelled);
        }
        if self.next_block != self.required_blocks {
            return Err(WatchdogError::Incomplete);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct QwenBlock0Receipt {
    pub descriptors_scanned: u32,
    pub tokens_completed: u32,
    pub attention_scores: u32,
    pub work: BlockWorkReceipt,
    pub token: [QwenBlockTokenReceipt; NP6_CONTEXT_TOKENS],
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct QwenBlockReceipt {
    pub block_index: u32,
    pub position: u32,
    pub context: u32,
    pub attention_scores: u32,
    pub work: BlockWorkReceipt,
    /// `embedding` in this compatibility-shaped stage receipt means the input
    /// hidden state for blocks after zero. The explicit block index prevents
    /// that field from being interpreted as a second embedding lookup.
    pub stages: QwenBlockTokenReceipt,
}

pub struct QwenBlock0Workspace<'a> {
    pub state: &'a mut [f32],
    pub norm: &'a mut [f32],
    pub query: &'a mut [f32],
    pub key_cache: &'a mut [f32],
    pub value_cache: &'a mut [f32],
    pub attention_context: &'a mut [f32],
    pub projected: &'a mut [f32],
    pub residual: &'a mut [f32],
    pub gate: &'a mut [f32],
    pub up: &'a mut [f32],
    pub activated: &'a mut [f32],
    pub down: &'a mut [f32],
    pub attention_weights: &'a mut [f32],
    pub attn_norm_weight: &'a mut [f32],
    pub query_norm_weight: &'a mut [f32],
    pub key_norm_weight: &'a mut [f32],
    pub ffn_norm_weight: &'a mut [f32],
    pub outputs: &'a mut [f32],
    /// Scratch used to reproduce ggml's Q8_K activation quantization before
    /// every Q4_K/Q6_K matrix product. It is not persistent model state.
    pub quantized_input: &'a mut [f32],
}

/// Execute one or two authentic token positions through Qwen3 block zero. A
/// single position is the strict NP6 guest gate; two positions exercise the
/// wider GQA path in the host oracle. Both stop before block one, output
/// normalization, logits, sampling, and token publication.
pub fn execute_qwen3_block0_np6<R: ReadAt>(
    source: &mut R,
    gguf: &PagedQwenGguf,
    tensors: QwenBlock0Tensors,
    embedding: TensorDescriptor,
    token_ids: [u32; NP6_CONTEXT_TOKENS],
    token_count: usize,
    workspace: &mut QwenBlock0Workspace<'_>,
) -> Result<QwenBlock0Receipt, Error> {
    let config = gguf.config();
    if !(1..=NP6_CONTEXT_TOKENS).contains(&token_count)
        || config.embedding_length as usize != QWEN3_EMBEDDING_LENGTH
        || config.feed_forward_length as usize != QWEN3_FFN_LENGTH
        || config.head_count as usize != QWEN3_Q_HEADS
        || config.head_count_kv as usize != QWEN3_KV_HEADS
        || config.rope_frequency_base.to_bits() != 1_000_000.0f32.to_bits()
        || workspace.state.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.norm.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.query.len() != QWEN3_Q_LENGTH
        || workspace.key_cache.len() != NP6_CONTEXT_TOKENS * QWEN3_KV_LENGTH
        || workspace.value_cache.len() != NP6_CONTEXT_TOKENS * QWEN3_KV_LENGTH
        || workspace.attention_context.len() != QWEN3_Q_LENGTH
        || workspace.projected.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.residual.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.gate.len() != QWEN3_FFN_LENGTH
        || workspace.up.len() != QWEN3_FFN_LENGTH
        || workspace.activated.len() != QWEN3_FFN_LENGTH
        || workspace.down.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.attention_weights.len() != QWEN3_Q_HEADS * NP6_CONTEXT_TOKENS
        || workspace.attn_norm_weight.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.query_norm_weight.len() != QWEN3_HEAD_DIMENSION
        || workspace.key_norm_weight.len() != QWEN3_HEAD_DIMENSION
        || workspace.ffn_norm_weight.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.outputs.len() != NP6_CONTEXT_TOKENS * QWEN3_EMBEDDING_LENGTH
        || workspace.quantized_input.len() < QWEN3_FFN_LENGTH
    {
        return Err(Error::Mismatch);
    }
    validate_block0_tensor_contract(tensors)?;
    read_f32_vector(source, tensors.attn_norm, workspace.attn_norm_weight)?;
    read_f32_vector(source, tensors.attn_q_norm, workspace.query_norm_weight)?;
    read_f32_vector(source, tensors.attn_k_norm, workspace.key_norm_weight)?;
    read_f32_vector(source, tensors.ffn_norm, workspace.ffn_norm_weight)?;

    let mut receipt = QwenBlock0Receipt {
        descriptors_scanned: tensors.descriptors_scanned,
        ..QwenBlock0Receipt::default()
    };
    for position in 0..token_count {
        let context = position + 1;
        let token_id = token_ids[position];
        read_q6_k_embedding_row(source, embedding, token_id, workspace.state)?;
        let mut token_receipt = QwenBlockTokenReceipt {
            token_id,
            position: position as u32,
            context: context as u32,
            embedding: StageSummary::from_values(workspace.state)?,
            ..QwenBlockTokenReceipt::default()
        };

        rms_norm(
            workspace.state,
            workspace.attn_norm_weight,
            config.rms_epsilon,
            workspace.norm,
        )?;
        token_receipt.attn_norm = StageSummary::from_values(workspace.norm)?;
        let matvec = quantized_matvec(source, tensors.attn_q, workspace.norm, workspace.query)?;
        accumulate_matvec(&mut receipt.work, matvec)?;
        token_receipt.query_projection = StageSummary::from_values(workspace.query)?;

        let key_start = position * QWEN3_KV_LENGTH;
        let key_end = key_start + QWEN3_KV_LENGTH;
        let current_key = &mut workspace.key_cache[key_start..key_end];
        let matvec = quantized_matvec(source, tensors.attn_k, workspace.norm, current_key)?;
        accumulate_matvec(&mut receipt.work, matvec)?;
        token_receipt.key_projection = StageSummary::from_values(current_key)?;

        let current_value = &mut workspace.value_cache[key_start..key_end];
        let matvec = quantized_matvec(source, tensors.attn_v, workspace.norm, current_value)?;
        accumulate_matvec(&mut receipt.work, matvec)?;
        token_receipt.value_projection = StageSummary::from_values(current_value)?;

        rms_norm_heads_in_place(
            workspace.query,
            workspace.query_norm_weight,
            QWEN3_Q_HEADS,
            config.rms_epsilon,
        )?;
        rms_norm_heads_in_place(
            current_key,
            workspace.key_norm_weight,
            QWEN3_KV_HEADS,
            config.rms_epsilon,
        )?;
        token_receipt.query_norm = StageSummary::from_values(workspace.query)?;
        token_receipt.key_norm = StageSummary::from_values(current_key)?;
        rope_qwen3_np6_in_place(
            workspace.query,
            QWEN3_Q_HEADS,
            position as u32,
            config.rope_frequency_base,
        )?;
        rope_qwen3_np6_in_place(
            current_key,
            QWEN3_KV_HEADS,
            position as u32,
            config.rope_frequency_base,
        )?;
        token_receipt.query_rope = StageSummary::from_values(workspace.query)?;
        token_receipt.key_rope = StageSummary::from_values(current_key)?;

        let attention_weight_values = QWEN3_Q_HEADS * context;
        grouped_query_attention_np6(
            workspace.query,
            &workspace.key_cache[..context * QWEN3_KV_LENGTH],
            &workspace.value_cache[..context * QWEN3_KV_LENGTH],
            QWEN3_Q_HEADS,
            QWEN3_KV_HEADS,
            QWEN3_HEAD_DIMENSION,
            context,
            workspace.attention_context,
            &mut workspace.attention_weights[..attention_weight_values],
        )?;
        receipt.attention_scores = receipt
            .attention_scores
            .checked_add(attention_weight_values as u32)
            .ok_or(Error::Bounds)?;
        token_receipt.attention_weights =
            StageSummary::from_values(&workspace.attention_weights[..attention_weight_values])?;
        token_receipt.attention_context = StageSummary::from_values(workspace.attention_context)?;

        let matvec = quantized_matvec(
            source,
            tensors.attn_output,
            workspace.attention_context,
            workspace.projected,
        )?;
        accumulate_matvec(&mut receipt.work, matvec)?;
        token_receipt.attention_projection = StageSummary::from_values(workspace.projected)?;
        for index in 0..QWEN3_EMBEDDING_LENGTH {
            workspace.residual[index] = workspace.state[index] + workspace.projected[index];
        }
        token_receipt.attention_residual = StageSummary::from_values(workspace.residual)?;

        rms_norm(
            workspace.residual,
            workspace.ffn_norm_weight,
            config.rms_epsilon,
            workspace.norm,
        )?;
        token_receipt.ffn_norm = StageSummary::from_values(workspace.norm)?;
        let matvec = quantized_matvec(source, tensors.ffn_gate, workspace.norm, workspace.gate)?;
        accumulate_matvec(&mut receipt.work, matvec)?;
        token_receipt.ffn_gate = StageSummary::from_values(workspace.gate)?;
        let matvec = quantized_matvec(source, tensors.ffn_up, workspace.norm, workspace.up)?;
        accumulate_matvec(&mut receipt.work, matvec)?;
        token_receipt.ffn_up = StageSummary::from_values(workspace.up)?;
        swiglu(workspace.gate, workspace.up, workspace.activated)?;
        token_receipt.ffn_activated = StageSummary::from_values(workspace.activated)?;
        let matvec = quantized_matvec(
            source,
            tensors.ffn_down,
            workspace.activated,
            workspace.down,
        )?;
        accumulate_matvec(&mut receipt.work, matvec)?;
        token_receipt.ffn_down = StageSummary::from_values(workspace.down)?;
        let output = &mut workspace.outputs
            [position * QWEN3_EMBEDDING_LENGTH..(position + 1) * QWEN3_EMBEDDING_LENGTH];
        for index in 0..QWEN3_EMBEDDING_LENGTH {
            output[index] = workspace.residual[index] + workspace.down[index];
        }
        token_receipt.block_output = StageSummary::from_values(output)?;
        receipt.token[position] = token_receipt;
        receipt.tokens_completed += 1;
    }
    Ok(receipt)
}

/// Execute one token position through one arbitrary Qwen3 block. The caller
/// owns the hidden state and the per-layer KV region. No embedding lookup,
/// output normalization, logits, sampling, or publication happens here.
pub fn execute_qwen3_block_np7<R: ReadAt>(
    source: &mut R,
    gguf: &PagedQwenGguf,
    block_index: u32,
    tensors: QwenBlock0Tensors,
    token_id: u32,
    position: usize,
    workspace: &mut QwenBlock0Workspace<'_>,
) -> Result<QwenBlockReceipt, Error> {
    let config = gguf.config();
    let context = position.checked_add(1).ok_or(Error::Bounds)?;
    if block_index >= config.block_count
        || context > NP7_MAX_CONTEXT_TOKENS
        || config.embedding_length as usize != QWEN3_EMBEDDING_LENGTH
        || config.feed_forward_length as usize != QWEN3_FFN_LENGTH
        || config.head_count as usize != QWEN3_Q_HEADS
        || config.head_count_kv as usize != QWEN3_KV_HEADS
        || config.rope_frequency_base.to_bits() != 1_000_000.0f32.to_bits()
        || workspace.state.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.norm.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.query.len() != QWEN3_Q_LENGTH
        || workspace.key_cache.len() < context * QWEN3_KV_LENGTH
        || workspace.value_cache.len() < context * QWEN3_KV_LENGTH
        || workspace.attention_context.len() != QWEN3_Q_LENGTH
        || workspace.projected.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.residual.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.gate.len() != QWEN3_FFN_LENGTH
        || workspace.up.len() != QWEN3_FFN_LENGTH
        || workspace.activated.len() != QWEN3_FFN_LENGTH
        || workspace.down.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.attention_weights.len() < QWEN3_Q_HEADS * context
        || workspace.attn_norm_weight.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.query_norm_weight.len() != QWEN3_HEAD_DIMENSION
        || workspace.key_norm_weight.len() != QWEN3_HEAD_DIMENSION
        || workspace.ffn_norm_weight.len() != QWEN3_EMBEDDING_LENGTH
        || workspace.outputs.len() < QWEN3_EMBEDDING_LENGTH
        || workspace.quantized_input.len() < QWEN3_FFN_LENGTH
    {
        return Err(Error::Mismatch);
    }
    validate_block0_tensor_contract(tensors)?;
    read_f32_vector(source, tensors.attn_norm, workspace.attn_norm_weight)?;
    read_f32_vector(source, tensors.attn_q_norm, workspace.query_norm_weight)?;
    read_f32_vector(source, tensors.attn_k_norm, workspace.key_norm_weight)?;
    read_f32_vector(source, tensors.ffn_norm, workspace.ffn_norm_weight)?;

    let mut receipt = QwenBlockReceipt {
        block_index,
        position: u32::try_from(position).map_err(|_| Error::Bounds)?,
        context: u32::try_from(context).map_err(|_| Error::Bounds)?,
        ..QwenBlockReceipt::default()
    };
    let mut stages = QwenBlockTokenReceipt {
        token_id,
        position: receipt.position,
        context: receipt.context,
        embedding: StageSummary::from_values(workspace.state)?,
        ..QwenBlockTokenReceipt::default()
    };

    rms_norm(
        workspace.state,
        workspace.attn_norm_weight,
        config.rms_epsilon,
        workspace.norm,
    )?;
    stages.attn_norm = StageSummary::from_values(workspace.norm)?;
let observed = quantized_matvec_q8_k_packed(
        source,
        tensors.attn_q,
        workspace.norm,
        workspace.query,
    )?;
    accumulate_matvec(&mut receipt.work, observed)?;
    stages.query_projection = StageSummary::from_values(workspace.query)?;

    let key_start = position * QWEN3_KV_LENGTH;
    let key_end = key_start + QWEN3_KV_LENGTH;
    let current_key = &mut workspace.key_cache[key_start..key_end];
let observed = quantized_matvec_q8_k_packed(
        source,
        tensors.attn_k,
        workspace.norm,
        current_key,
    )?;
    accumulate_matvec(&mut receipt.work, observed)?;
    stages.key_projection = StageSummary::from_values(current_key)?;
    let current_value = &mut workspace.value_cache[key_start..key_end];
let observed = quantized_matvec_q8_k_packed(
        source,
        tensors.attn_v,
        workspace.norm,
        current_value,
    )?;
    accumulate_matvec(&mut receipt.work, observed)?;
    stages.value_projection = StageSummary::from_values(current_value)?;

    rms_norm_heads_in_place(
        workspace.query,
        workspace.query_norm_weight,
        QWEN3_Q_HEADS,
        config.rms_epsilon,
    )?;
    rms_norm_heads_in_place(
        current_key,
        workspace.key_norm_weight,
        QWEN3_KV_HEADS,
        config.rms_epsilon,
    )?;
    stages.query_norm = StageSummary::from_values(workspace.query)?;
    stages.key_norm = StageSummary::from_values(current_key)?;
    rope_qwen3_in_place(
        workspace.query,
        QWEN3_Q_HEADS,
        receipt.position,
        config.rope_frequency_base,
    )?;
    rope_qwen3_in_place(
        current_key,
        QWEN3_KV_HEADS,
        receipt.position,
        config.rope_frequency_base,
    )?;
    stages.query_rope = StageSummary::from_values(workspace.query)?;
    stages.key_rope = StageSummary::from_values(current_key)?;

    let attention_values = QWEN3_Q_HEADS * context;
    grouped_query_attention_bounded(
        workspace.query,
        &workspace.key_cache[..context * QWEN3_KV_LENGTH],
        &workspace.value_cache[..context * QWEN3_KV_LENGTH],
        QWEN3_Q_HEADS,
        QWEN3_KV_HEADS,
        QWEN3_HEAD_DIMENSION,
        context,
        workspace.attention_context,
        &mut workspace.attention_weights[..attention_values],
    )?;
    receipt.attention_scores = u32::try_from(attention_values).map_err(|_| Error::Bounds)?;
    stages.attention_weights =
        StageSummary::from_values(&workspace.attention_weights[..attention_values])?;
    stages.attention_context = StageSummary::from_values(workspace.attention_context)?;

let observed = quantized_matvec_q8_k_packed(
        source,
        tensors.attn_output,
        workspace.attention_context,
        workspace.projected,
    )?;
    accumulate_matvec(&mut receipt.work, observed)?;
    stages.attention_projection = StageSummary::from_values(workspace.projected)?;
    for index in 0..QWEN3_EMBEDDING_LENGTH {
        workspace.residual[index] = workspace.state[index] + workspace.projected[index];
    }
    stages.attention_residual = StageSummary::from_values(workspace.residual)?;

    rms_norm(
        workspace.residual,
        workspace.ffn_norm_weight,
        config.rms_epsilon,
        workspace.norm,
    )?;
    stages.ffn_norm = StageSummary::from_values(workspace.norm)?;
let observed = quantized_matvec_q8_k_packed(
        source,
        tensors.ffn_gate,
        workspace.norm,
        workspace.gate,
    )?;
    accumulate_matvec(&mut receipt.work, observed)?;
    stages.ffn_gate = StageSummary::from_values(workspace.gate)?;
let observed = quantized_matvec_q8_k_packed(
        source,
        tensors.ffn_up,
        workspace.norm,
        workspace.up,
    )?;
    accumulate_matvec(&mut receipt.work, observed)?;
    stages.ffn_up = StageSummary::from_values(workspace.up)?;
    swiglu(workspace.gate, workspace.up, workspace.activated)?;
    stages.ffn_activated = StageSummary::from_values(workspace.activated)?;
let observed = quantized_matvec_q8_k_packed(
        source,
        tensors.ffn_down,
        workspace.activated,
        workspace.down,
    )?;
    accumulate_matvec(&mut receipt.work, observed)?;
    stages.ffn_down = StageSummary::from_values(workspace.down)?;
    for index in 0..QWEN3_EMBEDDING_LENGTH {
        workspace.outputs[index] = workspace.residual[index] + workspace.down[index];
    }
    stages.block_output = StageSummary::from_values(&workspace.outputs[..QWEN3_EMBEDDING_LENGTH])?;
    workspace
        .state
        .copy_from_slice(&workspace.outputs[..QWEN3_EMBEDDING_LENGTH]);
    receipt.stages = stages;
    Ok(receipt)
}

fn validate_block0_tensor_contract(tensors: QwenBlock0Tensors) -> Result<(), Error> {
    fn matrix(tensor: TensorDescriptor, input: usize, output: usize, ggml_type: u32) -> bool {
        tensor.dimension_count == 2
            && tensor.dimensions[0] == input as u64
            && tensor.dimensions[1] == output as u64
            && tensor.ggml_type == ggml_type
    }
    fn vector(tensor: TensorDescriptor, values: usize) -> bool {
        tensor.dimension_count == 1
            && tensor.dimensions[0] == values as u64
            && tensor.ggml_type == 0
    }
    fn q4_or_q6_matrix(tensor: TensorDescriptor, input: usize, output: usize) -> bool {
        tensor.dimension_count == 2
            && tensor.dimensions[0] == input as u64
            && tensor.dimensions[1] == output as u64
            && matches!(tensor.ggml_type, GGML_TYPE_Q4_K | GGML_TYPE_Q6_K)
    }
    if matrix(tensors.attn_q, 2_560, 4_096, GGML_TYPE_Q4_K)
        && matrix(tensors.attn_k, 2_560, 1_024, GGML_TYPE_Q4_K)
        && q4_or_q6_matrix(tensors.attn_v, 2_560, 1_024)
        && matrix(tensors.attn_output, 4_096, 2_560, GGML_TYPE_Q4_K)
        && matrix(tensors.ffn_gate, 2_560, 9_728, GGML_TYPE_Q4_K)
        && matrix(tensors.ffn_up, 2_560, 9_728, GGML_TYPE_Q4_K)
        && q4_or_q6_matrix(tensors.ffn_down, 9_728, 2_560)
        && vector(tensors.attn_norm, 2_560)
        && vector(tensors.attn_q_norm, 128)
        && vector(tensors.attn_k_norm, 128)
        && vector(tensors.ffn_norm, 2_560)
    {
        Ok(())
    } else {
        Err(Error::Mismatch)
    }
}

fn accumulate_matvec(total: &mut BlockWorkReceipt, observed: MatVecReceipt) -> Result<(), Error> {
    total.matvec_calls = total.matvec_calls.checked_add(1).ok_or(Error::Bounds)?;
    total.quantized_blocks = total
        .quantized_blocks
        .checked_add(observed.quantized_blocks)
        .ok_or(Error::Bounds)?;
    total.weight_bytes_read = total
        .weight_bytes_read
        .checked_add(observed.weight_bytes_read)
        .ok_or(Error::Bounds)?;
    total.multiply_accumulates = total
        .multiply_accumulates
        .checked_add(observed.multiply_accumulates)
        .ok_or(Error::Bounds)?;
    Ok(())
}

fn sqrt_f32(value: f32) -> Result<f32, Error> {
    if !value.is_finite() || value <= 0.0 {
        return Err(Error::NonFinite);
    }
    // Exponent-derived initial estimate followed by Newton refinement keeps
    // this no_std primitive bounded and independent of a platform libm.
    let mut estimate = f32::from_bits((value.to_bits() >> 1) + 0x1fc0_0000);
    for _ in 0..6 {
        estimate = 0.5 * (estimate + value / estimate);
    }
    Ok(estimate)
}

fn nearest_int_ggml(value: f32) -> Result<i32, Error> {
    if !value.is_finite() || value.abs() > 4_194_303.0 {
        return Err(Error::Quantization);
    }
    // Bit-exact scalar construction used by ggml's reference quantizer.  The
    // 2^23 + 2^22 offset makes IEEE-754 round-to-nearest-even observable
    // without depending on a platform libm routine.
    let rounded = value + 12_582_912.0f32;
    Ok(((rounded.to_bits() & 0x007f_ffff) as i32) - 0x0040_0000)
}

fn sin_cos_unit(value: f32) -> (f32, f32) {
    // NP6 admits theta in [0, 1]. Taylor orders 11/10 are comfortably below
    // the independent-oracle tolerance on that interval.
    let square = value * value;
    let sine = value
        * (1.0
            + square
                * (-1.0 / 6.0
                    + square * (1.0 / 120.0 + square * (-1.0 / 5040.0 + square / 362_880.0))));
    let cosine = 1.0
        + square
            * (-1.0 / 2.0 + square * (1.0 / 24.0 + square * (-1.0 / 720.0 + square / 40_320.0)));
    (sine, cosine)
}

fn sin_cos_bounded(value: f32) -> (f32, f32) {
    const PI: f32 = core::f32::consts::PI;
    const TAU: f32 = core::f32::consts::TAU;
    let turns = (value / TAU) as i32;
    let mut reduced = value - turns as f32 * TAU;
    if reduced > PI {
        reduced -= TAU;
    } else if reduced < -PI {
        reduced += TAU;
    }
    let square = reduced * reduced;
    // The earlier order-13/12 Taylor pair was sufficient for the two-token
    // NP9 canary but drifted materially near +/-PI in a 50-position prompt.
    // Extend both Horner chains so truncation is below f32 resolution over the
    // complete reduced interval. This stays deterministic and freestanding.
    let sine = reduced
        * (1.0
            + square
                * (-1.0 / 6.0
                    + square
                        * (1.0 / 120.0
                            + square
                                * (-1.0 / 5_040.0
                                    + square
                                        * (1.0 / 362_880.0
                                            + square
                                                * (-1.0 / 39_916_800.0
                                                    + square
                                                        * (1.0 / 6_227_020_800.0
                                                            + square
                                                                * (-1.0
                                                                    / 1_307_674_368_000.0
                                                                    + square
                                                                        / 355_687_428_096_000.0))))))));
    let cosine = 1.0
        + square
            * (-1.0 / 2.0
                + square
                    * (1.0 / 24.0
                        + square
                            * (-1.0 / 720.0
                                + square
                                    * (1.0 / 40_320.0
                                        + square
                                            * (-1.0 / 3_628_800.0
                                                + square
                                                    * (1.0 / 479_001_600.0
                                                        + square
                                                            * (-1.0 / 87_178_291_200.0
                                                                + square
                                                                    / 20_922_789_888_000.0)))))));
    (sine, cosine)
}

fn exp_negative(value: f32) -> Result<f32, Error> {
    if !value.is_finite() || value > 0.000_001 {
        return Err(Error::NonFinite);
    }
    if value < -80.0 {
        return Ok(0.0);
    }
    const LN_2: f32 = 0.693_147_2;
    let exponent = (value / LN_2) as i32;
    let remainder = value - exponent as f32 * LN_2;
    // After base-2 range reduction the remainder is in [-ln(2), 0].  The
    // former fifth-order series had ~1e-4 worst-case error and accumulated
    // through attention and SwiGLU.  Order ten brings truncation below f32
    // resolution on the bounded interval without a host libm dependency.
    let mut polynomial = 1.0 / 3_628_800.0;
    polynomial = 1.0 / 362_880.0 + remainder * polynomial;
    polynomial = 1.0 / 40_320.0 + remainder * polynomial;
    polynomial = 1.0 / 5_040.0 + remainder * polynomial;
    polynomial = 1.0 / 720.0 + remainder * polynomial;
    polynomial = 1.0 / 120.0 + remainder * polynomial;
    polynomial = 1.0 / 24.0 + remainder * polynomial;
    polynomial = 1.0 / 6.0 + remainder * polynomial;
    polynomial = 1.0 / 2.0 + remainder * polynomial;
    polynomial = 1.0 + remainder * polynomial;
    polynomial = 1.0 + remainder * polynomial;
    let biased = exponent + 127;
    let scale = if biased <= 0 {
        0.0
    } else {
        f32::from_bits((biased as u32) << 23)
    };
    let result = polynomial * scale;
    if result.is_finite() && result >= 0.0 {
        Ok(result)
    } else {
        Err(Error::NonFinite)
    }
}

pub fn dequantize_q4_k_block(block: &[u8], output: &mut [f32; QK_K]) -> Result<(), Error> {
    if block.len() != Q4_K_BLOCK_BYTES {
        return Err(Error::Quantization);
    }
    let d = f16_to_f32(u16::from_le_bytes([block[0], block[1]]));
    let dmin = f16_to_f32(u16::from_le_bytes([block[2], block[3]]));
    if !d.is_finite() || !dmin.is_finite() {
        return Err(Error::NonFinite);
    }
    let scales = &block[4..16];
    let qs = &block[16..144];
    for group in 0..4usize {
        let (scale_low, minimum_low) = scale_min_k4(group * 2, scales);
        let (scale_high, minimum_high) = scale_min_k4(group * 2 + 1, scales);
        let base = group * 64;
        let qbase = group * 32;
        let scale_low = d * f32::from(scale_low);
        let minimum_low = dmin * f32::from(minimum_low);
        let scale_high = d * f32::from(scale_high);
        let minimum_high = dmin * f32::from(minimum_high);
        for lane in 0..32usize {
            output[base + lane] = scale_low * f32::from(qs[qbase + lane] & 0x0f) - minimum_low;
            output[base + 32 + lane] = scale_high * f32::from(qs[qbase + lane] >> 4) - minimum_high;
        }
    }
    if output.iter().all(|value| value.is_finite()) {
        Ok(())
    } else {
        Err(Error::NonFinite)
    }
}

pub fn dot_q4_k_block(block: &[u8], input: &[f32]) -> Result<f32, Error> {
    if block.len() != Q4_K_BLOCK_BYTES
        || input.len() != QK_K
        || input.iter().any(|value| !value.is_finite())
    {
        return Err(Error::Quantization);
    }
    let d = f16_to_f32(u16::from_le_bytes([block[0], block[1]]));
    let dmin = f16_to_f32(u16::from_le_bytes([block[2], block[3]]));
    if !d.is_finite() || !dmin.is_finite() {
        return Err(Error::NonFinite);
    }
    let scales = &block[4..16];
    let qs = &block[16..144];
    let mut sum = 0.0f32;
    for group in 0..4usize {
        let (scale_low, minimum_low) = scale_min_k4(group * 2, scales);
        let (scale_high, minimum_high) = scale_min_k4(group * 2 + 1, scales);
        let base = group * 64;
        let qbase = group * 32;
        let scale_low = d * f32::from(scale_low);
        let minimum_low = dmin * f32::from(minimum_low);
        let scale_high = d * f32::from(scale_high);
        let minimum_high = dmin * f32::from(minimum_high);
        for lane in 0..32usize {
            let decoded = scale_low * f32::from(qs[qbase + lane] & 0x0f) - minimum_low;
            sum += decoded * input[base + lane];
        }
        for lane in 0..32usize {
            let decoded = scale_high * f32::from(qs[qbase + lane] >> 4) - minimum_high;
            sum += decoded * input[base + 32 + lane];
        }
    }
    if sum.is_finite() {
        Ok(sum)
    } else {
        Err(Error::NonFinite)
    }
}

fn dot_q4_k_q8_k_packed(
    block: &[u8],
    q8: &[i8],
    q8_sums: &[i16],
    q8_scale: f32,
) -> Result<f32, Error> {
    if block.len() != Q4_K_BLOCK_BYTES
        || q8.len() != QK_K
        || q8_sums.len() != QK_K / 16
        || !q8_scale.is_finite()
    {
        return Err(Error::Quantization);
    }
    let d = f16_to_f32(u16::from_le_bytes([block[0], block[1]]));
    let dmin = f16_to_f32(u16::from_le_bytes([block[2], block[3]]));
    if !d.is_finite() || !dmin.is_finite() {
        return Err(Error::NonFinite);
    }
    let scales = &block[4..16];
    let qs = &block[16..144];
    let mut positive = 0.0f32;
    let mut minimum = 0.0f32;
    for group in 0..8usize {
        let (scale, min) = scale_min_k4(group, scales);
        let input_base = group * 32;
        let qbase = (group / 2) * 32;
        let mut dot = 0i32;
        for lane in 0..32usize {
            let weight = if group.is_multiple_of(2) {
                qs[qbase + lane] & 0x0f
            } else {
                qs[qbase + lane] >> 4
            };
            dot = dot
                .checked_add(i32::from(weight) * i32::from(q8[input_base + lane]))
                .ok_or(Error::Bounds)?;
        }
        let activation_sum = i32::from(q8_sums[group * 2]) + i32::from(q8_sums[group * 2 + 1]);
        positive += f32::from(scale) * dot as f32;
        minimum += f32::from(min) * activation_sum as f32;
    }
    let result = d * q8_scale * positive - dmin * q8_scale * minimum;
    if result.is_finite() {
        Ok(result)
    } else {
        Err(Error::NonFinite)
    }
}

pub fn dequantize_q6_k_block(block: &[u8], output: &mut [f32; QK_K]) -> Result<(), Error> {
    if block.len() != Q6_K_BLOCK_BYTES {
        return Err(Error::Quantization);
    }
    let ql = &block[..128];
    let qh = &block[128..192];
    let scales = &block[192..208];
    let d = f16_to_f32(u16::from_le_bytes([block[208], block[209]]));
    if !d.is_finite() {
        return Err(Error::NonFinite);
    }
    for half in 0..2usize {
        let ql_base = half * 64;
        let qh_base = half * 32;
        let scale_base = half * 8;
        let output_base = half * 128;
        for lane in 0..32usize {
            let scale_lane = lane / 16;
            let high = qh[qh_base + lane];
            let q1 = i16::from((ql[ql_base + lane] & 0x0f) | ((high & 0x03) << 4)) - 32;
            let q2 = i16::from((ql[ql_base + lane + 32] & 0x0f) | (((high >> 2) & 0x03) << 4)) - 32;
            let q3 = i16::from((ql[ql_base + lane] >> 4) | (((high >> 4) & 0x03) << 4)) - 32;
            let q4 = i16::from((ql[ql_base + lane + 32] >> 4) | (((high >> 6) & 0x03) << 4)) - 32;
            let s1 = scales[scale_base + scale_lane] as i8;
            let s2 = scales[scale_base + scale_lane + 2] as i8;
            let s3 = scales[scale_base + scale_lane + 4] as i8;
            let s4 = scales[scale_base + scale_lane + 6] as i8;
            output[output_base + lane] = d * f32::from(s1) * f32::from(q1);
            output[output_base + lane + 32] = d * f32::from(s2) * f32::from(q2);
            output[output_base + lane + 64] = d * f32::from(s3) * f32::from(q3);
            output[output_base + lane + 96] = d * f32::from(s4) * f32::from(q4);
        }
    }
    if output.iter().all(|value| value.is_finite()) {
        Ok(())
    } else {
        Err(Error::NonFinite)
    }
}

pub fn dot_q6_k_block(block: &[u8], input: &[f32]) -> Result<f32, Error> {
    if block.len() != Q6_K_BLOCK_BYTES
        || input.len() != QK_K
        || input.iter().any(|value| !value.is_finite())
    {
        return Err(Error::Quantization);
    }
    let ql = &block[..128];
    let qh = &block[128..192];
    let scales = &block[192..208];
    let d = f16_to_f32(u16::from_le_bytes([block[208], block[209]]));
    if !d.is_finite() {
        return Err(Error::NonFinite);
    }
    let mut sum = 0.0f32;
    for half in 0..2usize {
        let ql_base = half * 64;
        let qh_base = half * 32;
        let scale_base = half * 8;
        let output_base = half * 128;
        for lane in 0..32usize {
            let scale_lane = lane / 16;
            let high = qh[qh_base + lane];
            let q1 = i16::from((ql[ql_base + lane] & 0x0f) | ((high & 0x03) << 4)) - 32;
            let s1 = scales[scale_base + scale_lane] as i8;
            let decoded = d * f32::from(s1) * f32::from(q1);
            sum += decoded * input[output_base + lane];
        }
        for lane in 0..32usize {
            let scale_lane = lane / 16;
            let high = qh[qh_base + lane];
            let q2 = i16::from((ql[ql_base + lane + 32] & 0x0f) | (((high >> 2) & 0x03) << 4)) - 32;
            let s2 = scales[scale_base + scale_lane + 2] as i8;
            let decoded = d * f32::from(s2) * f32::from(q2);
            sum += decoded * input[output_base + lane + 32];
        }
        for lane in 0..32usize {
            let scale_lane = lane / 16;
            let high = qh[qh_base + lane];
            let q3 = i16::from((ql[ql_base + lane] >> 4) | (((high >> 4) & 0x03) << 4)) - 32;
            let s3 = scales[scale_base + scale_lane + 4] as i8;
            let decoded = d * f32::from(s3) * f32::from(q3);
            sum += decoded * input[output_base + lane + 64];
        }
        for lane in 0..32usize {
            let scale_lane = lane / 16;
            let high = qh[qh_base + lane];
            let q4 = i16::from((ql[ql_base + lane + 32] >> 4) | (((high >> 6) & 0x03) << 4)) - 32;
            let s4 = scales[scale_base + scale_lane + 6] as i8;
            let decoded = d * f32::from(s4) * f32::from(q4);
            sum += decoded * input[output_base + lane + 96];
        }
    }
    if sum.is_finite() {
        Ok(sum)
    } else {
        Err(Error::NonFinite)
    }
}

fn dot_q6_k_q8_k_packed(block: &[u8], q8: &[i8], q8_scale: f32) -> Result<f32, Error> {
    if block.len() != Q6_K_BLOCK_BYTES || q8.len() != QK_K || !q8_scale.is_finite() {
        return Err(Error::Quantization);
    }
    let ql = &block[..128];
    let qh = &block[128..192];
    let scales = &block[192..208];
    let d = f16_to_f32(u16::from_le_bytes([block[208], block[209]]));
    if !d.is_finite() {
        return Err(Error::NonFinite);
    }
    let mut dots = [0i32; QK_K / 16];
    for half in 0..2usize {
        let ql_base = half * 64;
        let qh_base = half * 32;
        let output_base = half * 128;
        for lane in 0..32usize {
            let high = qh[qh_base + lane];
            let values = [
                i16::from((ql[ql_base + lane] & 0x0f) | ((high & 0x03) << 4)) - 32,
                i16::from((ql[ql_base + lane + 32] & 0x0f) | (((high >> 2) & 0x03) << 4)) - 32,
                i16::from((ql[ql_base + lane] >> 4) | (((high >> 4) & 0x03) << 4)) - 32,
                i16::from((ql[ql_base + lane + 32] >> 4) | (((high >> 6) & 0x03) << 4)) - 32,
            ];
            for (quarter, value) in values.into_iter().enumerate() {
                let index = output_base + quarter * 32 + lane;
                let group = index / 16;
                dots[group] = dots[group]
                    .checked_add(i32::from(value) * i32::from(q8[index]))
                    .ok_or(Error::Bounds)?;
            }
        }
    }
    let mut integer_sum = 0i32;
    for group in 0..QK_K / 16 {
        integer_sum = integer_sum
            .checked_add(i32::from(scales[group] as i8) * dots[group])
            .ok_or(Error::Bounds)?;
    }
    let result = d * q8_scale * integer_sum as f32;
    if result.is_finite() {
        Ok(result)
    } else {
        Err(Error::NonFinite)
    }
}

pub fn f32_tensor_prefix(bytes: &[u8], output: &mut [f32]) -> Result<(), Error> {
    let required = output.len().checked_mul(4).ok_or(Error::Bounds)?;
    if bytes.len() < required {
        return Err(Error::Truncated);
    }
    for (index, slot) in output.iter_mut().enumerate() {
        let offset = index * 4;
        *slot = f32::from_bits(u32::from_le_bytes(
            bytes[offset..offset + 4]
                .try_into()
                .map_err(|_| Error::Truncated)?,
        ));
        if !slot.is_finite() {
            return Err(Error::NonFinite);
        }
    }
    Ok(())
}

pub fn deterministic_probe_input() -> [f32; QK_K] {
    let mut result = [0.0f32; QK_K];
    let mut index = 0usize;
    while index < QK_K {
        result[index] = ((index % 17) as i32 - 8) as f32 / 8.0;
        index += 1;
    }
    result
}

fn scale_min_k4(index: usize, scales: &[u8]) -> (u8, u8) {
    if index < 4 {
        (scales[index] & 0x3f, scales[index + 4] & 0x3f)
    } else {
        (
            (scales[index + 4] & 0x0f) | ((scales[index - 4] >> 6) << 4),
            (scales[index + 4] >> 4) | ((scales[index] >> 6) << 4),
        )
    }
}

pub fn f16_to_f32(value: u16) -> f32 {
    let sign = u32::from(value & 0x8000) << 16;
    let exponent = (value >> 10) & 0x1f;
    let fraction = u32::from(value & 0x03ff);
    let bits = match exponent {
        0 if fraction == 0 => sign,
        0 => {
            let mut fraction = fraction;
            let mut exponent = 113u32;
            while fraction & 0x0400 == 0 {
                fraction <<= 1;
                exponent -= 1;
            }
            sign | (exponent << 23) | ((fraction & 0x03ff) << 13)
        }
        31 => sign | 0x7f80_0000 | (fraction << 13),
        _ => sign | ((u32::from(exponent) + 112) << 23) | (fraction << 13),
    };
    f32::from_bits(bits)
}

fn read_string<'a>(bytes: &'a [u8], cursor: &mut usize) -> Result<&'a [u8], Error> {
    let length = take_u64(bytes, cursor)?;
    let length = usize::try_from(length).map_err(|_| Error::Bounds)?;
    let start = *cursor;
    advance(bytes, cursor, length)?;
    bytes.get(start..*cursor).ok_or(Error::Truncated)
}

fn read_key<'a>(bytes: &'a [u8], cursor: &mut usize) -> Result<&'a [u8], Error> {
    let length = take_u64(bytes, cursor)?;
    if length > MAX_NAME_BYTES {
        return Err(Error::Bounds);
    }
    let length = usize::try_from(length).map_err(|_| Error::Bounds)?;
    let start = *cursor;
    advance(bytes, cursor, length)?;
    bytes.get(start..*cursor).ok_or(Error::Truncated)
}

fn skip_string(bytes: &[u8], cursor: &mut usize) -> Result<(), Error> {
    let length = usize::try_from(take_u64(bytes, cursor)?).map_err(|_| Error::Bounds)?;
    advance(bytes, cursor, length)
}

fn skip_value(bytes: &[u8], cursor: &mut usize, value_type: u32, depth: u8) -> Result<(), Error> {
    let width = match value_type {
        TYPE_U8 | TYPE_I8 | TYPE_BOOL => Some(1usize),
        TYPE_U16 | TYPE_I16 => Some(2),
        TYPE_U32 | TYPE_I32 | TYPE_F32 => Some(4),
        TYPE_U64 | TYPE_I64 | TYPE_F64 => Some(8),
        TYPE_STRING | TYPE_ARRAY => None,
        _ => return Err(Error::Type),
    };
    if let Some(width) = width {
        return advance(bytes, cursor, width);
    }
    if value_type == TYPE_STRING {
        return skip_string(bytes, cursor);
    }
    if depth >= MAX_NESTING {
        return Err(Error::Bounds);
    }
    let element_type = take_u32(bytes, cursor)?;
    let count = take_u64(bytes, cursor)?;
    if count > MAX_ARRAY_ITEMS {
        return Err(Error::Count);
    }
    let fixed_width = match element_type {
        TYPE_U8 | TYPE_I8 | TYPE_BOOL => Some(1usize),
        TYPE_U16 | TYPE_I16 => Some(2),
        TYPE_U32 | TYPE_I32 | TYPE_F32 => Some(4),
        TYPE_U64 | TYPE_I64 | TYPE_F64 => Some(8),
        _ => None,
    };
    if let Some(width) = fixed_width {
        let count = usize::try_from(count).map_err(|_| Error::Bounds)?;
        return advance(
            bytes,
            cursor,
            count.checked_mul(width).ok_or(Error::Bounds)?,
        );
    }
    for _ in 0..count {
        skip_value(bytes, cursor, element_type, depth + 1)?;
    }
    Ok(())
}

fn align_up(value: usize, alignment: usize) -> Result<usize, Error> {
    let mask = alignment.checked_sub(1).ok_or(Error::Alignment)?;
    value
        .checked_add(mask)
        .map(|sum| sum & !mask)
        .ok_or(Error::Bounds)
}

fn advance(bytes: &[u8], cursor: &mut usize, length: usize) -> Result<(), Error> {
    let end = cursor.checked_add(length).ok_or(Error::Bounds)?;
    if end > bytes.len() {
        return Err(Error::Truncated);
    }
    *cursor = end;
    Ok(())
}

fn take_u32(bytes: &[u8], cursor: &mut usize) -> Result<u32, Error> {
    let value = read_u32(bytes, *cursor)?;
    advance(bytes, cursor, 4)?;
    Ok(value)
}

fn take_u64(bytes: &[u8], cursor: &mut usize) -> Result<u64, Error> {
    let value = read_u64(bytes, *cursor)?;
    advance(bytes, cursor, 8)?;
    Ok(value)
}

fn read_u32(bytes: &[u8], offset: usize) -> Result<u32, Error> {
    Ok(u32::from_le_bytes(
        bytes
            .get(offset..offset + 4)
            .ok_or(Error::Truncated)?
            .try_into()
            .map_err(|_| Error::Truncated)?,
    ))
}

fn read_u64(bytes: &[u8], offset: usize) -> Result<u64, Error> {
    Ok(u64::from_le_bytes(
        bytes
            .get(offset..offset + 8)
            .ok_or(Error::Truncated)?
            .try_into()
            .map_err(|_| Error::Truncated)?,
    ))
}

#[cfg(test)]
extern crate std;

#[cfg(test)]
mod tests {
    use super::*;
    use std::vec::Vec;

    struct SliceSource<'a> {
        bytes: &'a [u8],
        reads: usize,
        max_read: usize,
    }

    impl ReadAt for SliceSource<'_> {
        fn len(&self) -> u64 {
            self.bytes.len() as u64
        }

        fn read_exact_at(&mut self, offset: u64, output: &mut [u8]) -> Result<(), Error> {
            let start = usize::try_from(offset).map_err(|_| Error::Bounds)?;
            let end = start.checked_add(output.len()).ok_or(Error::Bounds)?;
            let source = self.bytes.get(start..end).ok_or(Error::Truncated)?;
            output.copy_from_slice(source);
            self.reads += 1;
            self.max_read = self.max_read.max(output.len());
            Ok(())
        }
    }

    fn string(bytes: &mut Vec<u8>, value: &str) {
        bytes.extend_from_slice(&(value.len() as u64).to_le_bytes());
        bytes.extend_from_slice(value.as_bytes());
    }

    fn metadata_u32(bytes: &mut Vec<u8>, key: &str, value: u32) {
        string(bytes, key);
        bytes.extend_from_slice(&TYPE_U32.to_le_bytes());
        bytes.extend_from_slice(&value.to_le_bytes());
    }

    fn metadata_f32(bytes: &mut Vec<u8>, key: &str, value: f32) {
        string(bytes, key);
        bytes.extend_from_slice(&TYPE_F32.to_le_bytes());
        bytes.extend_from_slice(&value.to_bits().to_le_bytes());
    }

    fn metadata_string(bytes: &mut Vec<u8>, key: &str, value: &str) {
        string(bytes, key);
        bytes.extend_from_slice(&TYPE_STRING.to_le_bytes());
        string(bytes, value);
    }

    fn fixture(block: &[u8; Q4_K_BLOCK_BYTES]) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(GGUF_MAGIC);
        bytes.extend_from_slice(&GGUF_VERSION_3.to_le_bytes());
        bytes.extend_from_slice(&1u64.to_le_bytes());
        bytes.extend_from_slice(&9u64.to_le_bytes());
        metadata_string(&mut bytes, "general.architecture", "qwen3");
        metadata_u32(&mut bytes, "general.alignment", 32);
        metadata_u32(&mut bytes, "qwen3.context_length", 32768);
        metadata_u32(&mut bytes, "qwen3.embedding_length", 2560);
        metadata_u32(&mut bytes, "qwen3.feed_forward_length", 9728);
        metadata_u32(&mut bytes, "qwen3.block_count", 36);
        metadata_u32(&mut bytes, "qwen3.attention.head_count", 32);
        metadata_u32(&mut bytes, "qwen3.attention.head_count_kv", 8);
        metadata_f32(&mut bytes, "qwen3.rope.freq_base", 1_000_000.0);
        // Replace one count field with the last required scalar.
        let count_offset = 16;
        bytes[count_offset..count_offset + 8].copy_from_slice(&10u64.to_le_bytes());
        metadata_f32(&mut bytes, "qwen3.attention.layer_norm_rms_epsilon", 1e-6);
        string(&mut bytes, "casulo.probe.q4_k");
        bytes.extend_from_slice(&1u32.to_le_bytes());
        bytes.extend_from_slice(&256u64.to_le_bytes());
        bytes.extend_from_slice(&GGML_TYPE_Q4_K.to_le_bytes());
        bytes.extend_from_slice(&0u64.to_le_bytes());
        while !bytes.len().is_multiple_of(32) {
            bytes.push(0);
        }
        bytes.extend_from_slice(block);
        bytes
    }

    #[test]
    fn parses_qwen_projection_and_tensor() {
        let mut block = [0u8; Q4_K_BLOCK_BYTES];
        block[0..2].copy_from_slice(&0x3c00u16.to_le_bytes());
        block[2..4].copy_from_slice(&0x3800u16.to_le_bytes());
        block[4..16].fill(1);
        block[16..].fill(0x21);
        let bytes = fixture(&block);
        let gguf = Gguf::parse(&bytes).unwrap();
        assert_eq!(gguf.header().tensor_count, 1);
        assert_eq!(gguf.qwen_config().unwrap().block_count, 36);
        let tensor = gguf.tensor("casulo.probe.q4_k").unwrap();
        assert_eq!(tensor.byte_len, Q4_K_BLOCK_BYTES);
        assert_eq!(gguf.tensor_data(tensor).unwrap(), block);
    }

    #[test]
    fn block_tensor_names_are_structural_and_bounded() {
        assert_eq!(
            block_tensor_suffix(b"blk.35.ffn_up.weight", 35),
            Some(&b"ffn_up.weight"[..])
        );
        assert_eq!(block_tensor_suffix(b"blk.3.ffn_up.weight", 35), None);
        assert_eq!(block_tensor_suffix(b"blk.x.ffn_up.weight", 0), None);
        assert_eq!(block_tensor_suffix(b"output_norm.weight", 0), None);
    }

    #[test]
    fn decoder_watchdog_rejects_cancellation_reordering_and_incomplete_receipts() {
        let mut watchdog = DecoderBlockWatchdog::new(3).unwrap();
        assert_eq!(watchdog.begin_block(1), Err(WatchdogError::OutOfOrder));
        watchdog.complete_block(0).unwrap();
        assert_eq!(watchdog.finish(), Err(WatchdogError::Incomplete));
        watchdog.cancel();
        assert_eq!(watchdog.begin_block(1), Err(WatchdogError::Cancelled));

        let mut complete = DecoderBlockWatchdog::new(2).unwrap();
        complete.complete_block(0).unwrap();
        complete.complete_block(1).unwrap();
        assert_eq!(complete.completed_blocks(), 2);
        assert_eq!(complete.finish(), Ok(()));
    }

    #[test]
    fn paged_parser_never_materializes_the_gguf() {
        let mut block = [0u8; Q4_K_BLOCK_BYTES];
        block[0..2].copy_from_slice(&0x3c00u16.to_le_bytes());
        block[2..4].copy_from_slice(&0x3800u16.to_le_bytes());
        block[4..16].fill(1);
        block[16..].fill(0x21);
        let bytes = fixture(&block);
        let contiguous = Gguf::parse(&bytes).unwrap();
        let mut source = SliceSource {
            bytes: &bytes,
            reads: 0,
            max_read: 0,
        };
        let paged = PagedQwenGguf::parse(&mut source).unwrap();
        assert_eq!(
            paged.header().data_offset,
            contiguous.header().data_offset as u64
        );
        assert_eq!(paged.config(), contiguous.qwen_config().unwrap());
        let tensor = paged.tensor(&mut source, "casulo.probe.q4_k").unwrap();
        assert_eq!(tensor.ggml_type, GGML_TYPE_Q4_K);
        assert_eq!(tensor.byte_len, Q4_K_BLOCK_BYTES as u64);
        let mut observed = [0u8; Q4_K_BLOCK_BYTES];
        source
            .read_exact_at(tensor.absolute_offset, &mut observed)
            .unwrap();
        assert_eq!(observed, block);
        assert!(source.reads > 0);
        assert!(source.max_read <= Q4_K_BLOCK_BYTES);
    }

    #[test]
    fn q4_k_primitive_is_causal_and_bounded() {
        let mut a = [0u8; Q4_K_BLOCK_BYTES];
        a[0..2].copy_from_slice(&0x3c00u16.to_le_bytes());
        a[2..4].copy_from_slice(&0x3800u16.to_le_bytes());
        a[4..16].fill(3);
        a[16..].fill(0x21);
        let mut b = a;
        b[16] ^= 0x03;
        let input = deterministic_probe_input();
        let left = dot_q4_k_block(&a, &input).unwrap();
        let right = dot_q4_k_block(&b, &input).unwrap();
        assert!(left.is_finite());
        assert!(right.is_finite());
        assert_ne!(left.to_bits(), right.to_bits());
        assert_eq!(dot_q4_k_block(&a[..143], &input), Err(Error::Quantization));
    }

    #[test]
    fn q4_k_uses_eight_independent_scale_groups() {
        let mut block = [0u8; Q4_K_BLOCK_BYTES];
        block[0..2].copy_from_slice(&0x3c00u16.to_le_bytes()); // d = 1
        block[2..4].copy_from_slice(&0u16.to_le_bytes()); // dmin = 0
        block[4..16].copy_from_slice(&[1, 2, 3, 4, 0, 0, 0, 0, 5, 6, 7, 8]);
        block[16..].fill(0x11);
        let mut output = [0.0f32; QK_K];
        dequantize_q4_k_block(&block, &mut output).unwrap();
        for group in 0..8usize {
            assert!(
                output[group * 32..group * 32 + 32]
                    .iter()
                    .all(|value| *value == (group + 1) as f32)
            );
        }
    }

    #[test]
    fn q6_k_primitive_is_causal_and_bounded() {
        let mut a = [0u8; Q6_K_BLOCK_BYTES];
        for (index, byte) in a[..128].iter_mut().enumerate() {
            *byte = (index as u8).wrapping_mul(13);
        }
        for (index, byte) in a[128..192].iter_mut().enumerate() {
            *byte = (index as u8).wrapping_mul(7);
        }
        a[192..208].fill(2);
        a[208..210].copy_from_slice(&0x3c00u16.to_le_bytes());
        let mut b = a;
        b[0] ^= 1;
        let input = deterministic_probe_input();
        let left = dot_q6_k_block(&a, &input).unwrap();
        let right = dot_q6_k_block(&b, &input).unwrap();
        assert!(left.is_finite());
        assert!(right.is_finite());
        assert_ne!(left.to_bits(), right.to_bits());
        assert_eq!(dot_q6_k_block(&a[..209], &input), Err(Error::Quantization));
    }

    #[test]
    fn reads_f32_tensor_prefix_and_rejects_non_finite() {
        let bytes = [1.25f32.to_le_bytes(), (-2.5f32).to_le_bytes()].concat();
        let mut values = [0.0f32; 2];
        f32_tensor_prefix(&bytes, &mut values).unwrap();
        assert_eq!(values, [1.25, -2.5]);
        let bad = f32::NAN.to_le_bytes();
        assert_eq!(
            f32_tensor_prefix(&bad, &mut values[..1]),
            Err(Error::NonFinite)
        );
    }

    #[test]
    fn rejects_corruption_and_wrong_architecture() {
        let block = [0u8; Q4_K_BLOCK_BYTES];
        let mut bytes = fixture(&block);
        bytes[0] ^= 1;
        assert!(matches!(Gguf::parse(&bytes), Err(Error::Magic)));
    }

    fn string_array(bytes: &mut Vec<u8>, values: &[&str]) -> StringArrayDescriptor {
        let payload_offset = bytes.len() as u64;
        for value in values {
            string(bytes, value);
        }
        StringArrayDescriptor {
            count: values.len() as u64,
            payload_offset,
            end_offset: bytes.len() as u64,
        }
    }

    #[test]
    fn bounded_byte_bpe_is_causal_and_rejects_unsupported_scope() {
        let mut bytes = Vec::new();
        let merges = string_array(&mut bytes, &["C a", "Ca s", "u l", "ul o"]);
        let tokens = string_array(
            &mut bytes,
            &["C", "a", "s", "u", "l", "o", "Ca", "Cas", "ul", "ulo"],
        );
        let tokenizer = PagedTokenizer {
            tokens,
            merges,
            token_types: NumericArrayDescriptor {
                element_type: TYPE_I32,
                count: 10,
                payload_offset: 0,
                end_offset: 40,
            },
            chat_template: TextDescriptor {
                offset: 0,
                byte_len: 0,
            },
            bos_token_id: 0,
            eos_token_id: 1,
            padding_token_id: 0,
            add_bos_token: false,
        };
        let mut source = SliceSource {
            bytes: &bytes,
            reads: 0,
            max_read: 0,
        };
        let mut output = [0u32; 8];
        let receipt = tokenizer
            .tokenize_basic(&mut source, b"Casulo", &mut output)
            .unwrap();
        assert_eq!(&output[..receipt.output_tokens as usize], &[7, 9]);
        assert_eq!(receipt.pretokenized_pieces, 1);
        assert_eq!(receipt.merge_rules_scanned, 4);
        assert_eq!(
            tokenizer.tokenize_basic(&mut source, b"<|im_start|>", &mut output),
            Err(Error::Unsupported)
        );
        assert_eq!(
            tokenizer.tokenize_basic(&mut source, "漢".as_bytes(), &mut output),
            Err(Error::Unsupported)
        );
    }

    #[test]
    fn q6_embedding_row_is_selected_before_decode_and_bounded() {
        let mut bytes = std::vec![0u8; Q6_K_BLOCK_BYTES * 2];
        for row in 0..2usize {
            let start = row * Q6_K_BLOCK_BYTES;
            bytes[start + 192..start + 208].fill((row + 1) as u8);
            bytes[start + 208..start + 210].copy_from_slice(&0x3c00u16.to_le_bytes());
        }
        let descriptor = TensorDescriptor {
            dimensions: [256, 2, 0, 0],
            dimension_count: 2,
            ggml_type: GGML_TYPE_Q6_K,
            relative_offset: 0,
            absolute_offset: 0,
            byte_len: bytes.len() as u64,
        };
        let mut source = SliceSource {
            bytes: &bytes,
            reads: 0,
            max_read: 0,
        };
        let mut output = [0.0f32; 256];
        let receipt = read_q6_k_embedding_row(&mut source, descriptor, 1, &mut output).unwrap();
        assert_eq!(receipt.row_offset, Q6_K_BLOCK_BYTES as u64);
        assert_eq!(receipt.row_bytes, Q6_K_BLOCK_BYTES as u32);
        assert!(output.iter().all(|value| value.is_finite()));
        assert_eq!(
            read_q6_k_embedding_row(&mut source, descriptor, 2, &mut output),
            Err(Error::Mismatch)
        );
        assert_eq!(source.max_read, Q6_K_BLOCK_BYTES);
    }

    #[test]
    fn quantized_matvec_consumes_every_row_and_rejects_shape_drift() {
        let mut block = [0u8; Q4_K_BLOCK_BYTES];
        block[0..2].copy_from_slice(&0x3c00u16.to_le_bytes());
        block[2..4].copy_from_slice(&0u16.to_le_bytes());
        block[4..16].fill(1);
        block[16..].fill(0x11);
        let bytes = [block, block].concat();
        let descriptor = TensorDescriptor {
            dimensions: [256, 2, 0, 0],
            dimension_count: 2,
            ggml_type: GGML_TYPE_Q4_K,
            relative_offset: 0,
            absolute_offset: 0,
            byte_len: bytes.len() as u64,
        };
        let input = [1.0f32; 256];
        let mut output = [0.0f32; 2];
        let mut source = SliceSource {
            bytes: &bytes,
            reads: 0,
            max_read: 0,
        };
        let receipt = quantized_matvec(&mut source, descriptor, &input, &mut output).unwrap();
        assert_eq!(output, [256.0, 256.0]);
        assert_eq!(receipt.quantized_blocks, 2);
        assert_eq!(receipt.multiply_accumulates, 512);
        assert_eq!(source.reads, 2);
        assert_eq!(
            quantized_matvec(&mut source, descriptor, &input[..255], &mut output),
            Err(Error::Mismatch)
        );
    }

    #[test]
    fn fused_quantized_dots_are_bit_exact_with_materialized_reference() {
        let mut input = [0.0f32; QK_K];
        for (index, value) in input.iter_mut().enumerate() {
            *value = ((index as i32 % 19) - 9) as f32 * 0.03125;
        }

        let mut q4 = [0u8; Q4_K_BLOCK_BYTES];
        q4[0..2].copy_from_slice(&0x3400u16.to_le_bytes());
        q4[2..4].copy_from_slice(&0x2c00u16.to_le_bytes());
        for (index, byte) in q4[4..].iter_mut().enumerate() {
            *byte = (index as u8).wrapping_mul(37).wrapping_add(11);
        }
        let mut decoded_q4 = [0.0f32; QK_K];
        dequantize_q4_k_block(&q4, &mut decoded_q4).unwrap();
        let mut expected_q4 = 0.0f32;
        for index in 0..QK_K {
            expected_q4 += decoded_q4[index] * input[index];
        }
        assert_eq!(
            dot_q4_k_block(&q4, &input).unwrap().to_bits(),
            expected_q4.to_bits()
        );

        let mut q6 = [0u8; Q6_K_BLOCK_BYTES];
        for (index, byte) in q6[..208].iter_mut().enumerate() {
            *byte = (index as u8).wrapping_mul(29).wrapping_add(7);
        }
        q6[208..210].copy_from_slice(&0x3000u16.to_le_bytes());
        let mut decoded_q6 = [0.0f32; QK_K];
        dequantize_q6_k_block(&q6, &mut decoded_q6).unwrap();
        let mut expected_q6 = 0.0f32;
        for index in 0..QK_K {
            expected_q6 += decoded_q6[index] * input[index];
        }
        assert_eq!(
            dot_q6_k_block(&q6, &input).unwrap().to_bits(),
            expected_q6.to_bits()
        );
    }

    #[test]
    fn rms_norm_and_head_norm_are_causal() {
        let input = [3.0f32, 4.0];
        let weight = [1.0f32, 2.0];
        let mut output = [0.0f32; 2];
        rms_norm(&input, &weight, 1e-6, &mut output).unwrap();
        let expected_inverse = 1.0 / 12.500_001f32.sqrt();
        assert!((output[0] - 3.0 * expected_inverse).abs() < 1e-6);
        assert!((output[1] - 8.0 * expected_inverse).abs() < 1e-6);
        let mut heads = [3.0f32, 4.0, 6.0, 8.0];
        rms_norm_heads_in_place(&mut heads, &[1.0, 1.0], 2, 1e-6).unwrap();
        // RMS normalization is scale-invariant across proportional heads.
        assert!((heads[2] - heads[0]).abs() < 1e-6);
        assert!((heads[3] - heads[1]).abs() < 1e-6);
        assert_eq!(
            rms_norm_heads_in_place(&mut heads, &[1.0, 1.0], 3, 1e-6),
            Err(Error::Mismatch)
        );
    }

    #[test]
    fn rope_np6_changes_position_one_and_rejects_wider_context() {
        let mut position_zero = [0.0f32; 128];
        position_zero[0] = 1.0;
        let original = position_zero;
        rope_qwen3_np6_in_place(&mut position_zero, 1, 0, 1_000_000.0).unwrap();
        assert_eq!(position_zero, original);
        let mut position_one = original;
        rope_qwen3_np6_in_place(&mut position_one, 1, 1, 1_000_000.0).unwrap();
        assert!((position_one[0] - 1.0f32.cos()).abs() < 2e-5);
        assert_eq!(position_one[1], 0.0);
        assert!((position_one[64] - 1.0f32.sin()).abs() < 2e-5);
        assert_eq!(
            rope_qwen3_np6_in_place(&mut position_one, 1, 2, 1_000_000.0),
            Err(Error::Unsupported)
        );
    }

    #[test]
    fn rope_np7_supports_bounded_later_positions() {
        let mut values = [0.0f32; 128];
        values[0] = 1.0;
        rope_qwen3_in_place(&mut values, 1, 2, 1_000_000.0).unwrap();
        assert!((values[0] - 2.0f32.cos()).abs() < 2e-4);
        assert_eq!(values[1], 0.0);
        assert!((values[64] - 2.0f32.sin()).abs() < 2e-4);
        assert_eq!(
            rope_qwen3_in_place(&mut values, 1, 128, 1_000_000.0),
            Err(Error::Unsupported)
        );
    }

    #[test]
    fn grouped_query_attention_is_causal_and_normalized() {
        let query = [1.0f32, 0.0, 1.0, 0.0];
        // Two tokens, one KV head, two values per head. Both query heads share
        // the same KV head, which is the defining GQA mapping exercised here.
        let keys = [1.0f32, 0.0, 0.0, 1.0];
        let values = [2.0f32, 3.0, 10.0, 20.0];
        let mut output = [0.0f32; 4];
        let mut weights = [0.0f32; 4];
        grouped_query_attention_np6(
            &query,
            &keys,
            &values,
            2,
            1,
            2,
            2,
            &mut output,
            &mut weights,
        )
        .unwrap();
        assert!((weights[0] + weights[1] - 1.0).abs() < 1e-6);
        assert!((weights[2] + weights[3] - 1.0).abs() < 1e-6);
        assert!(output[0] > 2.0 && output[0] < 10.0);
        assert_eq!(output[..2], output[2..]);
    }

    #[test]
    fn grouped_query_attention_np7_accepts_three_tokens_but_np6_refuses() {
        let query = [1.0f32, 0.0];
        let keys = [1.0f32, 0.0, 0.0, 1.0, 1.0, 1.0];
        let values = [1.0f32, 2.0, 3.0, 4.0, 5.0, 6.0];
        let mut output = [0.0f32; 2];
        let mut weights = [0.0f32; 3];
        grouped_query_attention_bounded(
            &query,
            &keys,
            &values,
            1,
            1,
            2,
            3,
            &mut output,
            &mut weights,
        )
        .unwrap();
        assert!((weights.iter().sum::<f32>() - 1.0).abs() < 1e-6);
        assert_eq!(
            grouped_query_attention_np6(
                &query,
                &keys,
                &values,
                1,
                1,
                2,
                3,
                &mut output,
                &mut weights,
            ),
            Err(Error::Unsupported)
        );
    }

    #[test]
    fn swiglu_uses_both_branches_and_rejects_non_finite() {
        let gate = [-2.0f32, 0.0, 2.0];
        let up = [3.0f32, 4.0, 5.0];
        let mut output = [0.0f32; 3];
        swiglu(&gate, &up, &mut output).unwrap();
        assert!(output[0] < 0.0);
        assert_eq!(output[1], 0.0);
        assert!(output[2] > 0.0);
        assert_eq!(
            swiglu(&[f32::NAN], &[1.0], &mut output[..1]),
            Err(Error::NonFinite)
        );
    }
}
