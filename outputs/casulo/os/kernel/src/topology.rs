use core::arch::x86_64::{__cpuid, __cpuid_count};

pub struct CpuTopology {
    pub vendor: [u8; 12],
    pub logical_processors: u32,
    pub threads_per_core: u32,
    pub bsp_x2apic_id: u32,
    pub x2apic_supported: bool,
    pub hypervisor_present: bool,
}

impl CpuTopology {
    pub fn vendor_str(&self) -> &str {
        core::str::from_utf8(&self.vendor).unwrap_or("unknown")
    }
}

pub fn detect() -> CpuTopology {
    let basic = __cpuid(0);
    let mut vendor = [0u8; 12];
    vendor[0..4].copy_from_slice(&basic.ebx.to_le_bytes());
    vendor[4..8].copy_from_slice(&basic.edx.to_le_bytes());
    vendor[8..12].copy_from_slice(&basic.ecx.to_le_bytes());

    let leaf1 = __cpuid(1);
    let legacy_logical = ((leaf1.ebx >> 16) & 0xff).max(1);
    let mut logical_processors = legacy_logical;
    let mut threads_per_core = 1u32;
    let mut bsp_x2apic_id = (leaf1.ebx >> 24) & 0xff;

    if basic.eax >= 0x0b {
        for subleaf in 0..8 {
            let level = __cpuid_count(0x0b, subleaf);
            let level_type = (level.ecx >> 8) & 0xff;
            if level.ebx == 0 {
                break;
            }
            bsp_x2apic_id = level.edx;
            match level_type {
                1 => threads_per_core = level.ebx & 0xffff,
                2 => logical_processors = level.ebx & 0xffff,
                _ => {}
            }
        }
    }

    CpuTopology {
        vendor,
        logical_processors: logical_processors.max(1),
        threads_per_core: threads_per_core.max(1),
        bsp_x2apic_id,
        x2apic_supported: (leaf1.ecx & (1 << 21)) != 0,
        hypervisor_present: (leaf1.ecx & (1 << 31)) != 0,
    }
}
