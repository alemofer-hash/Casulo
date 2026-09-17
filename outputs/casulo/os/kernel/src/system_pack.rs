//! Bounded content-addressed system pack loaded as the UEFI ramdisk.

use sha2::{Digest, Sha256};

const MAGIC: &[u8; 8] = b"CSPK0001";
const VERSION: u32 = 1;
const DESCRIPTOR_BYTES: usize = 64;
const MAX_ENTRIES: usize = 9;

pub const KIND_BOOTSTRAP_TCAP: u32 = 1;
pub const KIND_UX_CONTRACT: u32 = 2;
pub const KIND_GUIDE_T_SOURCE: u32 = 3;
pub const KIND_MODEL_GGUF_PROBE: u32 = 4;
pub const KIND_NATIVE_SAMPLING_POLICY: u32 = 5;
pub const KIND_NATIVE_CREATION_PROMPT: u32 = 6;
pub const KIND_NATIVE_CREATION_ARTIFACT: u32 = 7;
pub const KIND_NATIVE_CREATION_ACCEPTANCE: u32 = 8;
pub const KIND_NATIVE_MODEL_GGUF: u32 = 9;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Reject {
    Header,
    Count,
    Truncated,
    Kind,
    Duplicate,
    Flags,
    Bounds,
    Overlap,
    Hash,
    TrailingBytes,
}

#[derive(Clone, Copy)]
pub struct Entry<'a> {
    pub kind: u32,
    pub payload: &'a [u8],
    #[allow(dead_code)]
    pub sha256: [u8; 32],
}

#[derive(Clone, Copy)]
pub struct Pack<'a> {
    entries: [Option<Entry<'a>>; MAX_ENTRIES],
    len: usize,
}

impl<'a> Pack<'a> {
    pub fn entry(&self, kind: u32) -> Option<Entry<'a>> {
        self.entries[..self.len]
            .iter()
            .flatten()
            .copied()
            .find(|entry| entry.kind == kind)
    }

    pub const fn len(&self) -> usize {
        self.len
    }
}

pub fn is_system_pack(bytes: &[u8]) -> bool {
    bytes.get(..8) == Some(MAGIC)
}

pub fn parse(bytes: &[u8]) -> Result<Pack<'_>, Reject> {
    if bytes.len() < 16 || !is_system_pack(bytes) || read_u32(bytes, 8)? != VERSION {
        return Err(Reject::Header);
    }
    let count = usize::try_from(read_u32(bytes, 12)?).map_err(|_| Reject::Count)?;
    if count == 0 || count > MAX_ENTRIES {
        return Err(Reject::Count);
    }
    let header_len = 16usize
        .checked_add(count.checked_mul(DESCRIPTOR_BYTES).ok_or(Reject::Bounds)?)
        .ok_or(Reject::Bounds)?;
    if bytes.len() < header_len {
        return Err(Reject::Truncated);
    }
    let mut entries: [Option<Entry<'_>>; MAX_ENTRIES] = [None; MAX_ENTRIES];
    let mut previous_end = header_len;
    for index in 0..count {
        let descriptor = 16 + index * DESCRIPTOR_BYTES;
        let kind = read_u32(bytes, descriptor)?;
        let flags = read_u32(bytes, descriptor + 4)?;
        let offset =
            usize::try_from(read_u64(bytes, descriptor + 8)?).map_err(|_| Reject::Bounds)?;
        let length =
            usize::try_from(read_u64(bytes, descriptor + 16)?).map_err(|_| Reject::Bounds)?;
        let reserved = read_u64(bytes, descriptor + 56)?;
        if !matches!(
            kind,
            KIND_BOOTSTRAP_TCAP
                | KIND_UX_CONTRACT
                | KIND_GUIDE_T_SOURCE
                | KIND_MODEL_GGUF_PROBE
                | KIND_NATIVE_SAMPLING_POLICY
                | KIND_NATIVE_CREATION_PROMPT
                | KIND_NATIVE_CREATION_ARTIFACT
                | KIND_NATIVE_CREATION_ACCEPTANCE
                | KIND_NATIVE_MODEL_GGUF
        ) {
            return Err(Reject::Kind);
        }
        if entries[..index]
            .iter()
            .flatten()
            .any(|entry| entry.kind == kind)
        {
            return Err(Reject::Duplicate);
        }
        if flags != 1 || reserved != 0 {
            return Err(Reject::Flags);
        }
        if length == 0 || offset < previous_end {
            return Err(Reject::Overlap);
        }
        let end = offset.checked_add(length).ok_or(Reject::Bounds)?;
        let payload = bytes.get(offset..end).ok_or(Reject::Bounds)?;
        let expected: [u8; 32] = bytes
            .get(descriptor + 24..descriptor + 56)
            .ok_or(Reject::Truncated)?
            .try_into()
            .map_err(|_| Reject::Truncated)?;
        let observed: [u8; 32] = Sha256::digest(payload).into();
        if observed != expected {
            return Err(Reject::Hash);
        }
        entries[index] = Some(Entry {
            kind,
            payload,
            sha256: expected,
        });
        previous_end = end;
    }
    if previous_end != bytes.len() {
        return Err(Reject::TrailingBytes);
    }
    Ok(Pack {
        entries,
        len: count,
    })
}

/// Exercise payload-integrity rejection without cloning a multi-gigabyte
/// physical ramdisk. The production pack itself is hashed by `parse` before
/// any entry is consumed; this bounded probe verifies the negative path.
pub fn bounded_corruption_probe() -> bool {
    const TOTAL: usize = 16 + DESCRIPTOR_BYTES + 1;
    let mut bytes = [0u8; TOTAL];
    bytes[..8].copy_from_slice(MAGIC);
    bytes[8..12].copy_from_slice(&VERSION.to_le_bytes());
    bytes[12..16].copy_from_slice(&1u32.to_le_bytes());
    let descriptor = 16;
    bytes[descriptor..descriptor + 4].copy_from_slice(&KIND_BOOTSTRAP_TCAP.to_le_bytes());
    bytes[descriptor + 4..descriptor + 8].copy_from_slice(&1u32.to_le_bytes());
    bytes[descriptor + 8..descriptor + 16]
        .copy_from_slice(&((16 + DESCRIPTOR_BYTES) as u64).to_le_bytes());
    bytes[descriptor + 16..descriptor + 24].copy_from_slice(&1u64.to_le_bytes());
    bytes[TOTAL - 1] = b'x';
    let expected: [u8; 32] = Sha256::digest([b'x']).into();
    bytes[descriptor + 24..descriptor + 56].copy_from_slice(&expected);
    if parse(&bytes).is_err() {
        return false;
    }
    bytes[TOTAL - 1] ^= 1;
    matches!(parse(&bytes), Err(Reject::Hash))
}

fn read_u32(bytes: &[u8], offset: usize) -> Result<u32, Reject> {
    Ok(u32::from_le_bytes(
        bytes
            .get(offset..offset + 4)
            .ok_or(Reject::Truncated)?
            .try_into()
            .map_err(|_| Reject::Truncated)?,
    ))
}

fn read_u64(bytes: &[u8], offset: usize) -> Result<u64, Reject> {
    Ok(u64::from_le_bytes(
        bytes
            .get(offset..offset + 8)
            .ok_or(Reject::Truncated)?
            .try_into()
            .map_err(|_| Reject::Truncated)?,
    ))
}
