//! Fail-closed TCAP v1 loader for the bounded Research Preview learn ABI.
//!
//! This module validates bytes in the bootloader ramdisk before any payload
//! page is mapped executable. It deliberately supports one frozen target/ABI;
//! an unknown extension is quarantined instead of being guessed.

use alloc::string::String;
use alloc::vec::Vec;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

const HEADER_LEN: usize = 32;
const MAX_FILE: usize = 64 * 1024 * 1024;
const MAX_MANIFEST: usize = 1024 * 1024;
const MAX_SEGMENTS: usize = 64;
const TARGET: &str = "x86_64-casulo-none";
const ABI: &str = "casulo-learn-context-sysv64/0.1";

#[derive(Clone, Copy)]
pub struct Segment<'a> {
    pub bytes: &'a [u8],
    pub alignment: usize,
}

pub struct Canary<'a> {
    pub bytes: &'a [u8],
    pub records: usize,
    pub inputs: usize,
    pub hidden: usize,
    pub outputs: usize,
    pub epochs: usize,
    pub parameters: usize,
    pub learning_rate: f64,
    pub target_loss: f64,
    pub tolerance: f64,
    pub expected_initial_loss: f64,
    pub expected_final_loss: f64,
}

impl Canary<'_> {
    pub fn inputs_bytes(&self) -> &[u8] {
        &self.bytes[80..592]
    }

    pub fn targets_bytes(&self) -> &[u8] {
        &self.bytes[592..656]
    }

    pub fn initial_parameters_bytes(&self) -> &[u8] {
        &self.bytes[656..1304]
    }

    pub fn expected_parameter(&self, index: usize) -> f64 {
        read_f64(self.bytes, 1304 + index * 8)
    }
}

pub struct Package<'a> {
    pub code: Segment<'a>,
    pub canary: Canary<'a>,
    pub entry_offset: usize,
    pub resource_memory_limit: u64,
    pub resource_arena_bytes: u64,
    pub raw_sha256: [u8; 32],
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Reject {
    Header,
    Manifest,
    Contract,
    Segment,
    Integrity,
    Canary,
}

pub fn parse(raw: &[u8]) -> Result<Package<'_>, Reject> {
    if raw.len() < HEADER_LEN || raw.len() > MAX_FILE || &raw[..4] != b"TCAP" {
        return Err(Reject::Header);
    }
    if read_u16(raw, 4) != 1 || read_u16(raw, 6) != 0 {
        return Err(Reject::Header);
    }
    let manifest_len = read_u32(raw, 8) as usize;
    let segment_count = read_u32(raw, 12) as usize;
    let payload_offset = usize::try_from(read_u64(raw, 16)).map_err(|_| Reject::Header)?;
    let file_len = usize::try_from(read_u64(raw, 24)).map_err(|_| Reject::Header)?;
    if !(1..=MAX_MANIFEST).contains(&manifest_len)
        || !(1..=MAX_SEGMENTS).contains(&segment_count)
        || file_len != raw.len()
        || payload_offset % 8 != 0
        || HEADER_LEN.checked_add(manifest_len).ok_or(Reject::Header)? > payload_offset
        || payload_offset > raw.len()
    {
        return Err(Reject::Header);
    }
    if raw[HEADER_LEN + manifest_len..payload_offset]
        .iter()
        .any(|byte| *byte != 0)
    {
        return Err(Reject::Header);
    }
    let manifest_raw = &raw[HEADER_LEN..HEADER_LEN + manifest_len];
    validate_canonical_json(manifest_raw)?;
    let manifest: Value = serde_json::from_slice(manifest_raw).map_err(|_| Reject::Manifest)?;
    let root = exact_object(
        &manifest,
        &[
            "abi",
            "compiler",
            "content_sha256",
            "energy",
            "entry_point",
            "resource_contract",
            "schema",
            "segments",
            "target",
        ],
    )?;
    if text(root, "schema")? != "tcap-manifest/1.0"
        || text(root, "target")? != TARGET
        || text(root, "abi")? != ABI
    {
        return Err(Reject::Contract);
    }
    validate_compiler(value(root, "compiler")?)?;
    let energy = exact_object(value(root, "energy")?, &["joules", "status"])?;
    if !matches!(value(energy, "joules")?, Value::Null) || text(energy, "status")? != "unavailable"
    {
        return Err(Reject::Contract);
    }
    let (memory_limit, arena_bytes) = validate_resource(value(root, "resource_contract")?)?;

    let entry = exact_object(value(root, "entry_point")?, &["offset", "segment"])?;
    if text(entry, "segment")? != "code" {
        return Err(Reject::Contract);
    }
    let entry_offset = uint(entry, "offset")? as usize;
    let descriptors = value(root, "segments")?.as_array().ok_or(Reject::Segment)?;
    if descriptors.len() != segment_count {
        return Err(Reject::Segment);
    }
    let mut segments: Vec<(String, String, Segment<'_>)> = Vec::with_capacity(segment_count);
    let mut occupied: Vec<(usize, usize)> = Vec::with_capacity(segment_count);
    let mut content = Sha256::new();
    for descriptor in descriptors {
        let object = exact_object(
            descriptor,
            &["alignment", "flags", "length", "name", "offset", "sha256"],
        )?;
        let name = text(object, "name")?;
        if name.is_empty() || name.len() > 128 || segments.iter().any(|item| item.0 == name) {
            return Err(Reject::Segment);
        }
        let flags = text(object, "flags")?;
        if flags.is_empty()
            || flags.len() > 3
            || flags.bytes().any(|flag| !b"rwx".contains(&flag))
            || flags.as_bytes().windows(2).any(|pair| pair[0] >= pair[1])
            || (flags.contains('w') && flags.contains('x'))
        {
            return Err(Reject::Segment);
        }
        let offset = usize::try_from(uint(object, "offset")?).map_err(|_| Reject::Segment)?;
        let length = usize::try_from(uint(object, "length")?).map_err(|_| Reject::Segment)?;
        let alignment = usize::try_from(uint(object, "alignment")?).map_err(|_| Reject::Segment)?;
        if length == 0
            || alignment == 0
            || alignment > 4096
            || !alignment.is_power_of_two()
            || offset % alignment != 0
        {
            return Err(Reject::Segment);
        }
        let end = offset.checked_add(length).ok_or(Reject::Segment)?;
        let absolute_start = payload_offset.checked_add(offset).ok_or(Reject::Segment)?;
        let absolute_end = payload_offset.checked_add(end).ok_or(Reject::Segment)?;
        if absolute_end > raw.len()
            || occupied
                .iter()
                .any(|(old_start, old_end)| offset < *old_end && *old_start < end)
        {
            return Err(Reject::Segment);
        }
        occupied.push((offset, end));
        let bytes = &raw[absolute_start..absolute_end];
        if !hash_matches(bytes, text(object, "sha256")?) {
            return Err(Reject::Integrity);
        }
        content.update((name.len() as u32).to_le_bytes());
        content.update(name.as_bytes());
        content.update((length as u64).to_le_bytes());
        content.update(bytes);
        segments.push((
            String::from(name),
            String::from(flags),
            Segment { bytes, alignment },
        ));
    }
    if !digest_matches(content.finalize().as_slice(), text(root, "content_sha256")?) {
        return Err(Reject::Integrity);
    }
    let (_, code_flags, code) = segments
        .iter()
        .find(|item| item.0 == "code")
        .ok_or(Reject::Segment)?;
    if code_flags != "rx"
        || entry_offset >= code.bytes.len()
        || code.bytes.is_empty()
        || code.bytes.len() > 3 * 4096 - 16
    {
        return Err(Reject::Contract);
    }
    let (_, canary_flags, canary_segment) = segments
        .iter()
        .find(|item| item.0 == "canary")
        .ok_or(Reject::Canary)?;
    if canary_flags != "r" || canary_segment.alignment < 8 {
        return Err(Reject::Canary);
    }
    let canary = parse_canary(canary_segment.bytes)?;
    Ok(Package {
        code: *code,
        canary,
        entry_offset,
        resource_memory_limit: memory_limit,
        resource_arena_bytes: arena_bytes,
        raw_sha256: Sha256::digest(raw).into(),
    })
}

fn validate_compiler(value: &Value) -> Result<(), Reject> {
    let object = exact_object(value, &["commit", "name", "version"])?;
    for key in ["commit", "name", "version"] {
        let item = text(object, key)?;
        if item.is_empty() || item.len() > 256 {
            return Err(Reject::Contract);
        }
    }
    Ok(())
}

fn validate_resource(input: &Value) -> Result<(u64, u64), Reject> {
    let resource = exact_object(
        input,
        &[
            "arena_bytes",
            "deadline_ns",
            "deterministic",
            "energy_budget_joules",
            "max_threads",
            "memory_limit_bytes",
            "numerical_precision",
            "permissions",
            "priority",
            "protocol",
            "quality_definition",
            "residual_routing",
            "semantic_class",
        ],
    )?;
    let memory = uint(resource, "memory_limit_bytes")?;
    let arena = uint(resource, "arena_bytes")?;
    if text(resource, "protocol")? != "casulo-resource-contract/1"
        || text(resource, "semantic_class")? != "FLOW"
        || text(resource, "numerical_precision")? != "float64"
        || value(resource, "deterministic")?.as_bool() != Some(true)
        || uint(resource, "max_threads")? != 1
        || uint(resource, "priority")? != 0
        || memory == 0
        || memory > 299_008
        || arena > 656
        || !matches!(value(resource, "deadline_ns")?, Value::Null)
        || !matches!(value(resource, "energy_budget_joules")?, Value::Null)
    {
        return Err(Reject::Contract);
    }
    let permissions = value(resource, "permissions")?
        .as_array()
        .ok_or(Reject::Contract)?;
    if permissions.len() != 2
        || permissions[0].as_str() != Some("memory")
        || permissions[1].as_str() != Some("console")
    {
        return Err(Reject::Contract);
    }
    let quality = exact_object(
        value(resource, "quality_definition")?,
        &[
            "loss",
            "max_abs_parameter_difference",
            "max_prediction_rmse_difference",
            "protocol",
            "target_loss",
        ],
    )?;
    if text(quality, "loss")? != "mse"
        || text(quality, "protocol")? != "casulo-learn-equivalence/0.1"
        || finite_positive(quality, "max_abs_parameter_difference")? > 1e-9
        || finite_positive(quality, "max_prediction_rmse_difference")? > 1e-9
        || finite_positive(quality, "target_loss")? > 0.08
    {
        return Err(Reject::Contract);
    }
    let residual = exact_object(
        value(resource, "residual_routing")?,
        &["audit", "invalid", "retry"],
    )?;
    if text(residual, "audit")? != "ATTRACTOR_AUDIT"
        || text(residual, "invalid")? != "QUARANTINE"
        || text(residual, "retry")? != "ATTRACTOR_RETRY"
    {
        return Err(Reject::Contract);
    }
    Ok((memory, arena))
}

fn parse_canary(bytes: &[u8]) -> Result<Canary<'_>, Reject> {
    if bytes.len() != 1952
        || &bytes[..8] != b"TCANARY\0"
        || read_u16(bytes, 8) != 1
        || read_u16(bytes, 10) != 0
        || read_u32(bytes, 12) != 80
        || read_u32(bytes, 16) != 8
        || read_u32(bytes, 20) != 8
        || read_u32(bytes, 24) != 8
        || read_u32(bytes, 28) != 1
        || read_u32(bytes, 32) != 400
        || read_u32(bytes, 36) != 81
    {
        return Err(Reject::Canary);
    }
    let values = [
        read_f64(bytes, 40),
        read_f64(bytes, 48),
        read_f64(bytes, 56),
        read_f64(bytes, 64),
        read_f64(bytes, 72),
    ];
    if values.iter().any(|number| !number.is_finite())
        || values[0] != 0.018
        || values[1] != 0.08
        || values[2] != 1e-9
        || values[3] != 0.551_408_730_000_000_1
        || values[4] != 0.007_241_680_427_492_191
    {
        return Err(Reject::Canary);
    }
    for offset in (80..1952).step_by(8) {
        if !read_f64(bytes, offset).is_finite() {
            return Err(Reject::Canary);
        }
    }
    Ok(Canary {
        bytes,
        records: 8,
        inputs: 8,
        hidden: 8,
        outputs: 1,
        epochs: 400,
        parameters: 81,
        learning_rate: values[0],
        target_loss: values[1],
        tolerance: values[2],
        expected_initial_loss: values[3],
        expected_final_loss: values[4],
    })
}

fn validate_canonical_json(raw: &[u8]) -> Result<(), Reject> {
    if core::str::from_utf8(raw).is_err() {
        return Err(Reject::Manifest);
    }
    let mut scanner = CanonicalScanner { raw, cursor: 0 };
    scanner.parse_value()?;
    if scanner.cursor != raw.len() {
        return Err(Reject::Manifest);
    }
    Ok(())
}

struct CanonicalScanner<'a> {
    raw: &'a [u8],
    cursor: usize,
}

impl CanonicalScanner<'_> {
    fn parse_value(&mut self) -> Result<(), Reject> {
        match self.peek()? {
            b'{' => self.parse_object(),
            b'[' => self.parse_array(),
            b'"' => self.parse_string().map(|_| ()),
            b't' => self.literal(b"true"),
            b'f' => self.literal(b"false"),
            b'n' => self.literal(b"null"),
            b'-' | b'0'..=b'9' => self.parse_number(),
            _ => Err(Reject::Manifest),
        }
    }

    fn parse_object(&mut self) -> Result<(), Reject> {
        self.take(b'{')?;
        let mut previous: Option<Vec<u8>> = None;
        if self.consume(b'}') {
            return Ok(());
        }
        loop {
            let key = self.parse_string()?;
            if key.contains(&b'\\') || previous.as_deref().is_some_and(|old| old >= key) {
                return Err(Reject::Manifest);
            }
            previous = Some(key.to_vec());
            self.take(b':')?;
            self.parse_value()?;
            if self.consume(b'}') {
                return Ok(());
            }
            self.take(b',')?;
        }
    }

    fn parse_array(&mut self) -> Result<(), Reject> {
        self.take(b'[')?;
        if self.consume(b']') {
            return Ok(());
        }
        loop {
            self.parse_value()?;
            if self.consume(b']') {
                return Ok(());
            }
            self.take(b',')?;
        }
    }

    fn parse_string(&mut self) -> Result<&[u8], Reject> {
        self.take(b'"')?;
        let start = self.cursor;
        let mut escaped = false;
        while self.cursor < self.raw.len() {
            let byte = self.raw[self.cursor];
            if byte < 0x20 {
                return Err(Reject::Manifest);
            }
            self.cursor += 1;
            if escaped {
                escaped = false;
                continue;
            }
            if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                return Ok(&self.raw[start..self.cursor - 1]);
            }
        }
        Err(Reject::Manifest)
    }

    fn parse_number(&mut self) -> Result<(), Reject> {
        let start = self.cursor;
        while self.cursor < self.raw.len()
            && matches!(
                self.raw[self.cursor],
                b'0'..=b'9' | b'-' | b'+' | b'.' | b'e' | b'E'
            )
        {
            self.cursor += 1;
        }
        if self.cursor == start {
            Err(Reject::Manifest)
        } else {
            Ok(())
        }
    }

    fn literal(&mut self, literal: &[u8]) -> Result<(), Reject> {
        if self.raw.get(self.cursor..self.cursor + literal.len()) == Some(literal) {
            self.cursor += literal.len();
            Ok(())
        } else {
            Err(Reject::Manifest)
        }
    }

    fn peek(&self) -> Result<u8, Reject> {
        self.raw.get(self.cursor).copied().ok_or(Reject::Manifest)
    }

    fn take(&mut self, expected: u8) -> Result<(), Reject> {
        if self.consume(expected) {
            Ok(())
        } else {
            Err(Reject::Manifest)
        }
    }

    fn consume(&mut self, expected: u8) -> bool {
        if self.raw.get(self.cursor) == Some(&expected) {
            self.cursor += 1;
            true
        } else {
            false
        }
    }
}

fn exact_object<'a>(value: &'a Value, keys: &[&str]) -> Result<&'a Map<String, Value>, Reject> {
    let object = value.as_object().ok_or(Reject::Manifest)?;
    if object.len() != keys.len() || keys.iter().any(|key| !object.contains_key(*key)) {
        return Err(Reject::Manifest);
    }
    Ok(object)
}

fn value<'a>(object: &'a Map<String, Value>, key: &str) -> Result<&'a Value, Reject> {
    object.get(key).ok_or(Reject::Manifest)
}

fn text<'a>(object: &'a Map<String, Value>, key: &str) -> Result<&'a str, Reject> {
    value(object, key)?.as_str().ok_or(Reject::Manifest)
}

fn uint(object: &Map<String, Value>, key: &str) -> Result<u64, Reject> {
    value(object, key)?.as_u64().ok_or(Reject::Manifest)
}

fn finite_positive(object: &Map<String, Value>, key: &str) -> Result<f64, Reject> {
    let number = value(object, key)?.as_f64().ok_or(Reject::Contract)?;
    if number.is_finite() && number > 0.0 {
        Ok(number)
    } else {
        Err(Reject::Contract)
    }
}

fn hash_matches(bytes: &[u8], expected: &str) -> bool {
    digest_matches(Sha256::digest(bytes).as_slice(), expected)
}

fn digest_matches(digest: &[u8], expected: &str) -> bool {
    if expected.len() != 64 {
        return false;
    }
    digest.iter().enumerate().all(|(index, byte)| {
        let high = hex(expected.as_bytes()[index * 2]);
        let low = hex(expected.as_bytes()[index * 2 + 1]);
        high != 0xff && low != 0xff && *byte == (high << 4 | low)
    })
}

fn hex(byte: u8) -> u8 {
    match byte {
        b'0'..=b'9' => byte - b'0',
        b'a'..=b'f' => byte - b'a' + 10,
        _ => 0xff,
    }
}

fn read_u16(bytes: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes(bytes[offset..offset + 2].try_into().unwrap())
}

fn read_u32(bytes: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
}

fn read_u64(bytes: &[u8], offset: usize) -> u64 {
    u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap())
}

fn read_f64(bytes: &[u8], offset: usize) -> f64 {
    f64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap())
}
