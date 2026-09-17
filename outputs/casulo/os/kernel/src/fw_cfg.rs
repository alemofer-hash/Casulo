//! Bounded read-only access to one externally provided QEMU fw_cfg item.
//!
//! The caller must already have admitted the exact owner model on the host.
//! This module has no path parser and cannot request another item. Externally
//! provided fw_cfg files are read-only to the guest by QEMU contract.

use casulo_native_model::{Error as ModelError, ReadAt};
use core::ptr::read_volatile;
use core::sync::atomic::{Ordering, compiler_fence};
use x86_64::instructions::port::Port;

use crate::memory::{DmaRegion, MemorySummary};

const SELECTOR_PORT: u16 = 0x510;
const DATA_PORT: u16 = 0x511;
const DMA_HIGH_PORT: u16 = 0x514;
const DMA_LOW_PORT: u16 = 0x518;
const SIGNATURE_ITEM: u16 = 0x0000;
const FEATURES_ITEM: u16 = 0x0001;
const FILE_DIRECTORY_ITEM: u16 = 0x0019;
const DMA_FEATURE: u32 = 1 << 1;
const DMA_ERROR: u32 = 1 << 0;
const DMA_READ: u32 = 1 << 1;
const DMA_SKIP: u32 = 1 << 2;
const DMA_SELECT: u32 = 1 << 3;
const DIRECTORY_ENTRY_BYTES: usize = 64;
const MAX_DIRECTORY_ENTRIES: u32 = 128;
const DMA_DESCRIPTOR_BYTES: usize = 16;
const DMA_DATA_OFFSET: usize = 64;
const RESIDENT_DMA_CHUNK_BYTES: usize = 64 * 1024 * 1024;
const DMA_SPIN_LIMIT: usize = 1_000_000;

pub const MODEL_ITEM_NAME: &[u8] = b"opt/com.teloscorp.casulo/model.gguf";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Reject {
    Signature,
    DmaUnavailable,
    DirectoryCount,
    DirectoryEntry,
    ModelMissing,
    ModelDuplicate,
    ModelSize,
    NoDmaPage,
    DmaAddress,
    DmaError,
    DmaTimeout,
    Bounds,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ReadStats {
    pub dma_operations: u64,
    pub cache_pages_loaded: u64,
    pub bytes_copied_to_consumer: u64,
    pub bytes_loaded_from_source: u64,
    pub largest_requested_end: u64,
}

pub struct ModelFile {
    selector: u16,
    size: u64,
    dma: DmaRegion,
    cache_offset: u64,
    cache_length: usize,
    cache_valid: bool,
    stats: ReadStats,
}

impl ModelFile {
    pub fn open(memory: &mut MemorySummary, expected_size: u64) -> Result<Self, Reject> {
        Self::open_with_profile(memory, expected_size, false)
    }

    pub fn open_resident(memory: &mut MemorySummary, expected_size: u64) -> Result<Self, Reject> {
        Self::open_with_profile(memory, expected_size, true)
    }

    fn open_with_profile(
        memory: &mut MemorySummary,
        expected_size: u64,
        resident: bool,
    ) -> Result<Self, Reject> {
        if pio_read_item::<4>(SIGNATURE_ITEM) != *b"QEMU" {
            return Err(Reject::Signature);
        }
        let features = u32::from_le_bytes(pio_read_item::<4>(FEATURES_ITEM));
        if features & DMA_FEATURE == 0 {
            return Err(Reject::DmaUnavailable);
        }
        let count = u32::from_be_bytes(pio_read_item::<4>(FILE_DIRECTORY_ITEM));
        if count == 0 || count > MAX_DIRECTORY_ENTRIES {
            return Err(Reject::DirectoryCount);
        }
        // Selecting the directory above positioned its stream immediately
        // after the count. Read every bounded entry exactly once.
        let mut found: Option<(u16, u64)> = None;
        for _ in 0..count {
            let entry = pio_read_data::<DIRECTORY_ENTRY_BYTES>();
            let size = u64::from(u32::from_be_bytes(
                entry[0..4].try_into().map_err(|_| Reject::DirectoryEntry)?,
            ));
            let selector =
                u16::from_be_bytes(entry[4..6].try_into().map_err(|_| Reject::DirectoryEntry)?);
            let name_end = entry[8..]
                .iter()
                .position(|byte| *byte == 0)
                .unwrap_or(entry.len() - 8);
            let name = &entry[8..8 + name_end];
            if name == MODEL_ITEM_NAME {
                if found.is_some() {
                    return Err(Reject::ModelDuplicate);
                }
                found = Some((selector, size));
            }
        }
        let (selector, size) = found.ok_or(Reject::ModelMissing)?;
        if size != expected_size {
            return Err(Reject::ModelSize);
        }
        #[cfg(casulo_native_model_resident)]
        let dma = if resident {
            memory
                .allocate_resident_model_region()
                .ok_or(Reject::NoDmaPage)?
        } else {
            memory.allocate_dma_region().ok_or(Reject::NoDmaPage)?
        };
        #[cfg(not(casulo_native_model_resident))]
        let dma = {
            if resident {
                return Err(Reject::Bounds);
            }
            memory.allocate_dma_region().ok_or(Reject::NoDmaPage)?
        };
        if dma
            .physical_address()
            .checked_add(dma.length() as u64)
            .is_none()
        {
            return Err(Reject::DmaAddress);
        }
        Ok(Self {
            selector,
            size,
            dma,
            cache_offset: 0,
            cache_length: 0,
            cache_valid: false,
            stats: ReadStats::default(),
        })
    }

    pub const fn stats(&self) -> ReadStats {
        self.stats
    }

    fn fill_cache(&mut self, offset: u64) -> Result<(), Reject> {
        if offset >= self.size {
            return Err(Reject::Bounds);
        }
        let cache_bytes = self
            .dma
            .length()
            .checked_sub(DMA_DATA_OFFSET)
            .ok_or(Reject::Bounds)?;
        if cache_bytes as u64 >= self.size {
            return self.fill_resident_cache();
        }
        let page = offset / cache_bytes as u64 * cache_bytes as u64;
        let remaining = self.size - page;
        let length =
            usize::try_from(remaining.min(cache_bytes as u64)).map_err(|_| Reject::Bounds)?;
        self.dma_select_and_skip(page)?;
        self.dma_read_into(length, DMA_DATA_OFFSET)?;
        self.cache_offset = page;
        self.cache_length = length;
        self.cache_valid = true;
        self.stats.cache_pages_loaded += 1;
        self.stats.bytes_loaded_from_source += length as u64;
        Ok(())
    }

    fn fill_resident_cache(&mut self) -> Result<(), Reject> {
        let mut offset = 0u64;
        while offset < self.size {
            let remaining = usize::try_from(self.size - offset).map_err(|_| Reject::Bounds)?;
            let length = remaining.min(RESIDENT_DMA_CHUNK_BYTES);
            let destination = DMA_DATA_OFFSET
                .checked_add(usize::try_from(offset).map_err(|_| Reject::Bounds)?)
                .ok_or(Reject::Bounds)?;
            self.dma_select_and_skip(offset)?;
            self.dma_read_into(length, destination)?;
            self.stats.cache_pages_loaded += 1;
            self.stats.bytes_loaded_from_source += length as u64;
            offset = offset.checked_add(length as u64).ok_or(Reject::Bounds)?;
        }
        self.cache_offset = 0;
        self.cache_length = usize::try_from(self.size).map_err(|_| Reject::Bounds)?;
        self.cache_valid = true;
        Ok(())
    }

    fn dma_select_and_skip(&mut self, offset: u64) -> Result<(), Reject> {
        let length = u32::try_from(offset).map_err(|_| Reject::Bounds)?;
        let control = (u32::from(self.selector) << 16) | DMA_SELECT | DMA_SKIP;
        self.dma_operation(control, length, 0)
    }

    fn dma_read_into(&mut self, length: usize, destination: usize) -> Result<(), Reject> {
        if destination
            .checked_add(length)
            .is_none_or(|end| end > self.dma.length())
        {
            return Err(Reject::Bounds);
        }
        let address = self
            .dma
            .physical_address()
            .checked_add(destination as u64)
            .ok_or(Reject::DmaAddress)?;
        self.dma_operation(
            DMA_READ,
            u32::try_from(length).map_err(|_| Reject::Bounds)?,
            address,
        )
    }

    fn dma_operation(&mut self, control: u32, length: u32, address: u64) -> Result<(), Reject> {
        let descriptor_physical = self.dma.physical_address();
        let bytes = unsafe { self.dma.bytes_mut() };
        bytes[..DMA_DESCRIPTOR_BYTES].fill(0);
        bytes[0..4].copy_from_slice(&control.to_be_bytes());
        bytes[4..8].copy_from_slice(&length.to_be_bytes());
        bytes[8..16].copy_from_slice(&address.to_be_bytes());
        compiler_fence(Ordering::Release);
        trigger_dma(descriptor_physical);
        let control_ptr = bytes.as_mut_ptr().cast::<u32>();
        for _ in 0..DMA_SPIN_LIMIT {
            compiler_fence(Ordering::Acquire);
            let observed = u32::from_be(unsafe { read_volatile(control_ptr) });
            if observed == 0 {
                self.stats.dma_operations += 1;
                return Ok(());
            }
            if observed & DMA_ERROR != 0 {
                return Err(Reject::DmaError);
            }
            core::hint::spin_loop();
        }
        Err(Reject::DmaTimeout)
    }
}

impl ReadAt for ModelFile {
    fn len(&self) -> u64 {
        self.size
    }

    fn read_exact_at(&mut self, offset: u64, output: &mut [u8]) -> Result<(), ModelError> {
        let output_len = u64::try_from(output.len()).map_err(|_| ModelError::Bounds)?;
        let end = offset.checked_add(output_len).ok_or(ModelError::Bounds)?;
        if end > self.size {
            return Err(ModelError::Truncated);
        }
        let mut source_offset = offset;
        let mut output_offset = 0usize;
        while output_offset < output.len() {
            let cached_end = self.cache_offset + self.cache_length as u64;
            if !self.cache_valid || source_offset < self.cache_offset || source_offset >= cached_end
            {
                self.fill_cache(source_offset)
                    .map_err(|_| ModelError::Source)?;
            }
            let within = usize::try_from(source_offset - self.cache_offset)
                .map_err(|_| ModelError::Bounds)?;
            let available = self.cache_length - within;
            let copied = available.min(output.len() - output_offset);
            let dma_bytes = unsafe { self.dma.bytes_mut() };
            output[output_offset..output_offset + copied].copy_from_slice(
                &dma_bytes[DMA_DATA_OFFSET + within..DMA_DATA_OFFSET + within + copied],
            );
            source_offset += copied as u64;
            output_offset += copied;
        }
        self.stats.bytes_copied_to_consumer += output.len() as u64;
        self.stats.largest_requested_end = self.stats.largest_requested_end.max(end);
        Ok(())
    }
}

fn pio_read_item<const N: usize>(selector: u16) -> [u8; N] {
    unsafe {
        let mut control: Port<u16> = Port::new(SELECTOR_PORT);
        control.write(selector);
    }
    pio_read_data::<N>()
}

fn pio_read_data<const N: usize>() -> [u8; N] {
    let mut output = [0u8; N];
    unsafe {
        let mut data: Port<u8> = Port::new(DATA_PORT);
        for byte in &mut output {
            *byte = data.read();
        }
    }
    output
}

fn trigger_dma(descriptor_physical: u64) {
    let high = (descriptor_physical >> 32) as u32;
    let low = descriptor_physical as u32;
    unsafe {
        let mut high_port: Port<u32> = Port::new(DMA_HIGH_PORT);
        let mut low_port: Port<u32> = Port::new(DMA_LOW_PORT);
        high_port.write(high.to_be());
        // Writing the least-significant half triggers the operation.
        low_port.write(low.to_be());
    }
}
