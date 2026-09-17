//! Content-free append-only persistence journal contract.
//!
//! The journal stores only hashes and ordering metadata. A storage adapter is
//! responsible for atomically persisting the canonical records and payloads.

use sha2::{Digest, Sha256};

pub const JOURNAL_SCHEMA: &str = "casulo.native-journal/0.1";
pub const MAX_JOURNAL_RECORDS: usize = 16;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum JournalError {
    EmptyPayload,
    CapacityExceeded,
    CorruptSequence,
    CorruptPreviousHash,
    CorruptRecordHash,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct JournalRecord {
    pub sequence: u32,
    pub kind: u16,
    pub payload_sha256: [u8; 32],
    pub previous_sha256: [u8; 32],
    pub record_sha256: [u8; 32],
}

impl JournalRecord {
    const fn empty() -> Option<Self> {
        None
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Journal {
    records: [Option<JournalRecord>; MAX_JOURNAL_RECORDS],
    len: usize,
}

impl Journal {
    pub const fn new() -> Self {
        Self {
            records: [JournalRecord::empty(); MAX_JOURNAL_RECORDS],
            len: 0,
        }
    }

    pub const fn len(&self) -> usize {
        self.len
    }

    pub const fn is_empty(&self) -> bool {
        self.len == 0
    }

    pub fn head(&self) -> [u8; 32] {
        self.records[..self.len]
            .last()
            .and_then(|record| *record)
            .map_or([0; 32], |record| record.record_sha256)
    }

    pub fn records(&self) -> impl Iterator<Item = &JournalRecord> {
        self.records[..self.len].iter().flatten()
    }

    pub fn append(&mut self, kind: u16, payload: &[u8]) -> Result<JournalRecord, JournalError> {
        if payload.is_empty() {
            return Err(JournalError::EmptyPayload);
        }
        if self.len == MAX_JOURNAL_RECORDS {
            return Err(JournalError::CapacityExceeded);
        }
        let sequence = self.len as u32 + 1;
        let previous_sha256 = self.head();
        let payload_sha256: [u8; 32] = Sha256::digest(payload).into();
        let record_sha256 = record_hash(sequence, kind, payload_sha256, previous_sha256);
        let record = JournalRecord {
            sequence,
            kind,
            payload_sha256,
            previous_sha256,
            record_sha256,
        };
        self.records[self.len] = Some(record);
        self.len += 1;
        Ok(record)
    }

    pub fn validate(&self) -> Result<(), JournalError> {
        let mut previous = [0; 32];
        for (index, record) in self.records().enumerate() {
            if record.sequence != index as u32 + 1 {
                return Err(JournalError::CorruptSequence);
            }
            if record.previous_sha256 != previous {
                return Err(JournalError::CorruptPreviousHash);
            }
            if record.record_sha256
                != record_hash(
                    record.sequence,
                    record.kind,
                    record.payload_sha256,
                    record.previous_sha256,
                )
            {
                return Err(JournalError::CorruptRecordHash);
            }
            previous = record.record_sha256;
        }
        Ok(())
    }
}

impl Default for Journal {
    fn default() -> Self {
        Self::new()
    }
}

pub fn self_test() -> bool {
    let mut journal = Journal::new();
    let first = journal.append(1, b"presence-ready");
    let second = journal.append(2, b"intent-confirmed");
    let valid = first.is_ok()
        && second.is_ok()
        && journal.len() == 2
        && journal.validate().is_ok()
        && journal.head().iter().any(|byte| *byte != 0);
    let mut corrupt = journal;
    if let Some(record) = corrupt.records[1].as_mut() {
        record.payload_sha256[0] ^= 1;
    }
    valid && corrupt.validate() == Err(JournalError::CorruptRecordHash)
}

fn record_hash(
    sequence: u32,
    kind: u16,
    payload_sha256: [u8; 32],
    previous_sha256: [u8; 32],
) -> [u8; 32] {
    let mut hash = Sha256::new();
    hash.update(JOURNAL_SCHEMA.as_bytes());
    hash.update(sequence.to_le_bytes());
    hash.update(kind.to_le_bytes());
    hash.update(payload_sha256);
    hash.update(previous_sha256);
    hash.finalize().into()
}
