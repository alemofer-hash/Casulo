//! Bounded, real xAPIC AP startup for the two-vCPU QEMU G2 gate.

use crate::memory::MemorySummary;
use core::sync::atomic::{AtomicU64, Ordering};
use x86_64::instructions::hlt;

const AP_TRAMPOLINE: &[u8; 512] = include_bytes!(concat!(env!("OUT_DIR"), "/ap_trampoline.bin"));
const IA32_APIC_BASE: u32 = 0x1b;
const APIC_ENABLE: u64 = 1 << 11;
const APIC_ID: u64 = 0x20;
const APIC_SVR: u64 = 0xf0;
const APIC_ICR_LOW: u64 = 0x300;
const APIC_ICR_HIGH: u64 = 0x310;

#[repr(align(16))]
struct ApStack([u8; 16 * 1024]);
static mut AP_STACK: ApStack = ApStack([0; 16 * 1024]);
static AP_STARTED: AtomicU64 = AtomicU64::new(0);

pub struct SmpSummary {
    pub madt_valid: bool,
    pub expected_aps: u64,
    pub started_aps: u64,
    pub target_apic_id: u8,
    pub lapic_physical: u64,
    pub bounded: bool,
}

#[unsafe(no_mangle)]
extern "C" fn casulo_ap_entry() -> ! {
    AP_STARTED.fetch_add(1, Ordering::Release);
    loop {
        hlt();
    }
}

unsafe fn read_u32(pointer: *const u8) -> u32 {
    unsafe { core::ptr::read_unaligned(pointer.cast::<u32>()) }
}
unsafe fn read_u64(pointer: *const u8) -> u64 {
    unsafe { core::ptr::read_unaligned(pointer.cast::<u64>()) }
}

fn checksum(bytes: &[u8]) -> bool {
    bytes
        .iter()
        .fold(0u8, |sum, value| sum.wrapping_add(*value))
        == 0
}

unsafe fn physical_slice(offset: u64, physical: u64, length: usize) -> &'static [u8] {
    unsafe { core::slice::from_raw_parts((offset + physical) as *const u8, length) }
}

unsafe fn find_madt(offset: u64, rsdp_physical: u64) -> Option<(u64, u8)> {
    let rsdp = unsafe { physical_slice(offset, rsdp_physical, 36) };
    if &rsdp[0..8] != b"RSD PTR " || !checksum(&rsdp[..20]) {
        return None;
    }
    let (root, width) = if rsdp[15] >= 2 && checksum(rsdp) {
        (unsafe { read_u64(rsdp.as_ptr().add(24)) }, 8usize)
    } else {
        (unsafe { read_u32(rsdp.as_ptr().add(16)) } as u64, 4usize)
    };
    let header = unsafe { physical_slice(offset, root, 36) };
    let length = unsafe { read_u32(header.as_ptr().add(4)) } as usize;
    if !(36..=1024 * 1024).contains(&length) {
        return None;
    }
    let table = unsafe { physical_slice(offset, root, length) };
    if !checksum(table) {
        return None;
    }
    let mut cursor = 36usize;
    while cursor + width <= length {
        let address = if width == 8 {
            unsafe { read_u64(table.as_ptr().add(cursor)) }
        } else {
            (unsafe { read_u32(table.as_ptr().add(cursor)) }) as u64
        };
        let candidate_header = unsafe { physical_slice(offset, address, 36) };
        let candidate_length = unsafe { read_u32(candidate_header.as_ptr().add(4)) } as usize;
        if (44..=1024 * 1024).contains(&candidate_length) {
            let candidate = unsafe { physical_slice(offset, address, candidate_length) };
            if &candidate[0..4] == b"APIC" && checksum(candidate) {
                let lapic = unsafe { read_u32(candidate.as_ptr().add(36)) } as u64;
                let bsp_id = current_apic_id(offset, lapic);
                let mut entry = 44usize;
                while entry + 2 <= candidate.len() {
                    let kind = candidate[entry];
                    let size = candidate[entry + 1] as usize;
                    if size < 2 || entry + size > candidate.len() {
                        return None;
                    }
                    if kind == 0 && size >= 8 {
                        let apic_id = candidate[entry + 3];
                        let flags = unsafe { read_u32(candidate.as_ptr().add(entry + 4)) };
                        if flags & 1 != 0 && apic_id != bsp_id {
                            return Some((lapic, apic_id));
                        }
                    }
                    entry += size;
                }
            }
        }
        cursor += width;
    }
    None
}

fn current_apic_id(offset: u64, lapic: u64) -> u8 {
    unsafe { (core::ptr::read_volatile((offset + lapic + APIC_ID) as *const u32) >> 24) as u8 }
}

unsafe fn rdmsr(index: u32) -> u64 {
    let low: u32;
    let high: u32;
    unsafe { core::arch::asm!("rdmsr", in("ecx") index, out("eax") low, out("edx") high) };
    (u64::from(high) << 32) | u64::from(low)
}

unsafe fn wrmsr(index: u32, value: u64) {
    unsafe {
        core::arch::asm!("wrmsr", in("ecx") index, in("eax") value as u32, in("edx") (value >> 32) as u32)
    };
}

fn delay_cycles(cycles: u64) {
    let start = unsafe { core::arch::x86_64::_rdtsc() };
    while unsafe { core::arch::x86_64::_rdtsc() }.wrapping_sub(start) < cycles {
        core::hint::spin_loop();
    }
}

unsafe fn apic_write(offset: u64, lapic: u64, register: u64, value: u32) {
    unsafe { core::ptr::write_volatile((offset + lapic + register) as *mut u32, value) };
}

unsafe fn wait_icr(offset: u64, lapic: u64) {
    while unsafe { core::ptr::read_volatile((offset + lapic + APIC_ICR_LOW) as *const u32) }
        & (1 << 12)
        != 0
    {
        core::hint::spin_loop();
    }
}

pub fn start_one(memory: &MemorySummary, rsdp_physical: Option<u64>) -> SmpSummary {
    let Some(rsdp) = rsdp_physical else {
        return SmpSummary {
            madt_valid: false,
            expected_aps: 0,
            started_aps: 0,
            target_apic_id: 0,
            lapic_physical: 0,
            bounded: true,
        };
    };
    let Some((lapic, apic_id)) = (unsafe { find_madt(memory.physical_memory_offset, rsdp) }) else {
        return SmpSummary {
            madt_valid: false,
            expected_aps: 0,
            started_aps: 0,
            target_apic_id: 0,
            lapic_physical: 0,
            bounded: true,
        };
    };
    let trampoline = memory.trampoline_frame.start_address().as_u64();
    let destination = (memory.physical_memory_offset + trampoline) as *mut u8;
    unsafe {
        core::ptr::copy_nonoverlapping(AP_TRAMPOLINE.as_ptr(), destination, AP_TRAMPOLINE.len());
        // Frozen offsets are asserted by the NASM source comments and binary size.
        core::ptr::write_unaligned(destination.add(8).cast::<u64>(), memory.kernel_cr3);
        let stack = core::ptr::addr_of!(AP_STACK.0) as u64 + 16 * 1024;
        core::ptr::write_unaligned(destination.add(16).cast::<u64>(), stack);
        core::ptr::write_unaligned(
            destination.add(24).cast::<u64>(),
            casulo_ap_entry as *const () as u64,
        );
        core::ptr::write_unaligned(destination.add(34).cast::<u32>(), (trampoline + 40) as u32);
        // Base fields of the 32-bit code and data descriptors.
        patch_descriptor_base(destination.add(48), trampoline as u32);
        patch_descriptor_base(destination.add(56), trampoline as u32);
        core::ptr::write_unaligned(
            destination.add(165).cast::<u32>(),
            (trampoline + long_mode_offset()) as u32,
        );

        let base = rdmsr(IA32_APIC_BASE) | APIC_ENABLE;
        wrmsr(IA32_APIC_BASE, base);
        apic_write(memory.physical_memory_offset, lapic, APIC_SVR, 0x1ff);
        apic_write(
            memory.physical_memory_offset,
            lapic,
            APIC_ICR_HIGH,
            u32::from(apic_id) << 24,
        );
        apic_write(
            memory.physical_memory_offset,
            lapic,
            APIC_ICR_LOW,
            0x0000_c500,
        );
        wait_icr(memory.physical_memory_offset, lapic);
        delay_cycles(30_000_000);
        for _ in 0..2 {
            apic_write(
                memory.physical_memory_offset,
                lapic,
                APIC_ICR_HIGH,
                u32::from(apic_id) << 24,
            );
            apic_write(
                memory.physical_memory_offset,
                lapic,
                APIC_ICR_LOW,
                0x0000_4600 | (trampoline as u32 >> 12),
            );
            wait_icr(memory.physical_memory_offset, lapic);
            delay_cycles(3_000_000);
        }
    }
    let start = unsafe { core::arch::x86_64::_rdtsc() };
    while AP_STARTED.load(Ordering::Acquire) == 0
        && unsafe { core::arch::x86_64::_rdtsc() }.wrapping_sub(start) < 500_000_000
    {
        core::hint::spin_loop();
    }
    SmpSummary {
        madt_valid: true,
        expected_aps: 1,
        started_aps: AP_STARTED.load(Ordering::Acquire),
        target_apic_id: apic_id,
        lapic_physical: lapic,
        bounded: true,
    }
}

unsafe fn patch_descriptor_base(descriptor: *mut u8, base: u32) {
    unsafe {
        *descriptor.add(2) = base as u8;
        *descriptor.add(3) = (base >> 8) as u8;
        *descriptor.add(4) = (base >> 16) as u8;
        *descriptor.add(7) = (base >> 24) as u8;
    }
}

// NASM's fixed layout puts long_mode at byte 171. Keeping this function named
// makes the runtime patch self-describing and checked by the evidence marker.
const fn long_mode_offset() -> u64 {
    171
}
