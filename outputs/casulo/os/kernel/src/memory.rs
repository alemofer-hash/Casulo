use bootloader_api::info::{MemoryRegion, MemoryRegionKind};
use core::alloc::{GlobalAlloc, Layout};
use core::ptr::null_mut;
use core::sync::atomic::{AtomicBool, Ordering};
use x86_64::registers::control::Cr3;
use x86_64::structures::paging::mapper::TranslateResult;
use x86_64::structures::paging::{
    FrameAllocator, Mapper, OffsetPageTable, Page, PageSize, PageTable, PageTableFlags, PhysFrame,
    Size4KiB, Translate,
};
use x86_64::{PhysAddr, VirtAddr};

pub const HEAP_START: u64 = 0x_5555_0000_0000;
// T/2.0 conformance parses a bounded, self-contained TCAP with typed IR and
// provenance. Two MiB remains tiny relative to the 256 MiB guest profile while
// avoiding an implicit dependency on host-side parsing.
// The ordinary product image keeps the original two-MiB heap. NP7 opts into a
// bounded 16-MiB heap so its eight-MiB read-only GGUF cache and sub-MiB decoder
// arena coexist without changing any other build profile. NP10 holds 96 token
// positions of K/V state for every adopted-model layer and uses a bump arena
// whose deallocations are intentionally no-ops; its explicit 64-MiB ceiling
// accommodates those caches plus tokenizer, logits and T receipt state.
#[cfg(casulo_native_creation)]
pub const HEAP_SIZE: usize = 64 * 1024 * 1024;
#[cfg(all(not(casulo_native_creation), casulo_native_model_decoder))]
pub const HEAP_SIZE: usize = 16 * 1024 * 1024;
#[cfg(all(not(casulo_native_creation), not(casulo_native_model_decoder)))]
pub const HEAP_SIZE: usize = 2 * 1024 * 1024;
pub const GUARD_PAGE: u64 = HEAP_START + HEAP_SIZE as u64;

pub struct MemorySummary {
    pub usable_bytes: u64,
    pub usable_frames: u64,
    pub heap_pages: u64,
    pub heap_kernel_only: bool,
    pub guard_unmapped: bool,
    pub user_address_space: UserAddressSpace,
    pub user_code_rx: bool,
    pub user_stack_nx: bool,
    pub low_usable_frame: Option<PhysFrame>,
    pub trampoline_frame: PhysFrame,
    pub kernel_cr3: u64,
    pub physical_memory_offset: u64,
    pub kernel_user_inaccessible: bool,
    pub user_paging_branch_private: bool,
    frame_allocator: BootInfoFrameAllocator,
}

/// A bounded run of physically contiguous, directly mapped pages reserved for
/// read-only model prefetch. Ownership remains with the kernel and the address
/// is never exposed to ring 3.
pub struct DmaRegion {
    physical_address: u64,
    virtual_address: *mut u8,
    length: usize,
}

impl DmaRegion {
    // fw_cfg DMA itself remains read-only. NP7 raises only the bounded cache
    // window, from 256 KiB to eight MiB, avoiding thousands of VM exits while
    // still keeping over 99% of the 2.49-GB model non-resident.
    // NP9 admits the exact adopted GGUF and then keeps its read-only bytes in
    // guest-owned RAM. This removes fw_cfg VM exits from the decoder hot path;
    // it does not duplicate the model on disk or relax the model hash gate.
    #[cfg(casulo_native_model_decoder)]
    pub const PAGED_PAGES: usize = 2_048;
    #[cfg(not(casulo_native_model_decoder))]
    pub const PAGED_PAGES: usize = 64;
    pub const RESIDENT_PAGES: usize = 609_688;

    pub const fn physical_address(&self) -> u64 {
        self.physical_address
    }

    pub const fn length(&self) -> usize {
        self.length
    }

    pub unsafe fn bytes_mut(&mut self) -> &mut [u8] {
        unsafe { core::slice::from_raw_parts_mut(self.virtual_address, self.length) }
    }
}

#[derive(Clone, Copy)]
pub struct UserAddressSpace {
    pub level_4_frame: PhysFrame,
}

#[derive(Clone, Copy)]
pub struct LearnAddressSpace {
    pub address_space: UserAddressSpace,
    pub entry: u64,
    pub stack_pointer: u64,
    pub context_pointer: u64,
    pub permission_probe_entry: u64,
    pub data_physical: u64,
    pub code_rx: bool,
    pub data_rw_nx: bool,
    pub stack_rw_nx: bool,
    pub mapped_user_bytes: u64,
}

#[derive(Clone, Copy)]
pub struct ProbeAddressSpace {
    pub address_space: UserAddressSpace,
    pub private_page_mapped: bool,
}

#[repr(C)]
struct LearnContextRaw {
    inputs: u64,
    targets: u64,
    parameters: u64,
    gradients: u64,
    records: usize,
    epochs: usize,
    learning_rate: f64,
    initial_loss: u64,
    final_loss: u64,
}

/// Frame allocator backed exclusively by UEFI regions tagged `Usable`.
///
/// The boot information has static lifetime. We keep a raw, read-only view so that the
/// allocator cannot mutate or accidentally reclassify firmware-owned ranges.
pub struct BootInfoFrameAllocator {
    regions: *const MemoryRegion,
    region_count: usize,
    region_index: usize,
    next_address: u64,
}

unsafe impl Send for BootInfoFrameAllocator {}

impl BootInfoFrameAllocator {
    pub fn new(regions: &'static [MemoryRegion]) -> Self {
        Self {
            regions: regions.as_ptr(),
            region_count: regions.len(),
            region_index: 0,
            next_address: 0,
        }
    }
}

unsafe impl FrameAllocator<Size4KiB> for BootInfoFrameAllocator {
    fn allocate_frame(&mut self) -> Option<PhysFrame> {
        let regions = unsafe { core::slice::from_raw_parts(self.regions, self.region_count) };
        while self.region_index < regions.len() {
            let region = &regions[self.region_index];
            if region.kind != MemoryRegionKind::Usable {
                self.region_index += 1;
                self.next_address = 0;
                continue;
            }
            let start = region.start.saturating_add(Size4KiB::SIZE - 1) & !(Size4KiB::SIZE - 1);
            let end = region.end & !(Size4KiB::SIZE - 1);
            let address = self.next_address.max(start);
            if address < end {
                self.next_address = address.saturating_add(Size4KiB::SIZE);
                return Some(PhysFrame::containing_address(PhysAddr::new(address)));
            }
            self.region_index += 1;
            self.next_address = 0;
        }
        None
    }
}

struct BumpState {
    next: usize,
    end: usize,
}

pub struct LockedBump {
    locked: AtomicBool,
    state: core::cell::UnsafeCell<BumpState>,
}

unsafe impl Sync for LockedBump {}

impl LockedBump {
    const fn empty() -> Self {
        Self {
            locked: AtomicBool::new(false),
            state: core::cell::UnsafeCell::new(BumpState { next: 0, end: 0 }),
        }
    }

    pub unsafe fn init(&self, start: usize, size: usize) {
        self.lock();
        let state = unsafe { &mut *self.state.get() };
        state.next = start;
        state.end = start.saturating_add(size);
        self.unlock();
    }

    fn lock(&self) {
        while self
            .locked
            .compare_exchange_weak(false, true, Ordering::Acquire, Ordering::Relaxed)
            .is_err()
        {
            core::hint::spin_loop();
        }
    }

    fn unlock(&self) {
        self.locked.store(false, Ordering::Release);
    }
}

#[global_allocator]
static ALLOCATOR: LockedBump = LockedBump::empty();

unsafe impl GlobalAlloc for LockedBump {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        self.lock();
        let state = unsafe { &mut *self.state.get() };
        let aligned = state
            .next
            .checked_add(layout.align() - 1)
            .map(|value| value & !(layout.align() - 1));
        let allocation =
            aligned.and_then(|start| start.checked_add(layout.size()).map(|end| (start, end)));
        let result = match allocation {
            Some((start, end)) if end <= state.end => {
                state.next = end;
                start as *mut u8
            }
            _ => null_mut(),
        };
        self.unlock();
        result
    }

    unsafe fn dealloc(&self, _ptr: *mut u8, _layout: Layout) {
        // Research Preview 0.1 uses a bounded boot-time arena. Individual frees are a no-op.
    }
}

pub unsafe fn initialize(
    physical_memory_offset: u64,
    regions: &'static [MemoryRegion],
    user_image: &[u8],
) -> MemorySummary {
    let usable_bytes = regions
        .iter()
        .filter(|region| region.kind == MemoryRegionKind::Usable)
        .map(|region| region.end.saturating_sub(region.start))
        .sum::<u64>();
    let usable_frames = regions
        .iter()
        .filter(|region| region.kind == MemoryRegionKind::Usable)
        .map(|region| {
            let start = region.start.saturating_add(Size4KiB::SIZE - 1) & !(Size4KiB::SIZE - 1);
            let end = region.end & !(Size4KiB::SIZE - 1);
            end.saturating_sub(start) / Size4KiB::SIZE
        })
        .sum::<u64>();
    let low_usable_frame = regions
        .iter()
        .filter(|region| region.kind == MemoryRegionKind::Usable)
        .flat_map(|region| {
            let start = region.start.saturating_add(4095) & !4095;
            let end = core::cmp::min(region.end & !4095, 0x10_0000);
            (start..end).step_by(4096)
        })
        .find(|address| *address >= 0x1000)
        .map(|address| PhysFrame::containing_address(PhysAddr::new(address)));

    let level_4_frame = Cr3::read().0;
    let level_4_virtual =
        VirtAddr::new(physical_memory_offset + level_4_frame.start_address().as_u64());
    let active_level_4_ptr = level_4_virtual.as_ptr::<PageTable>();
    let level_4_table = unsafe { &mut *level_4_virtual.as_mut_ptr::<PageTable>() };
    let mut mapper =
        unsafe { OffsetPageTable::new(level_4_table, VirtAddr::new(physical_memory_offset)) };
    let mut frame_allocator = BootInfoFrameAllocator::new(regions);
    let mut trampoline_frame = frame_allocator
        .allocate_frame()
        .expect("no frame for the AP trampoline");
    while trampoline_frame.start_address().as_u64() < 0x1000 {
        trampoline_frame = frame_allocator
            .allocate_frame()
            .expect("no non-null frame for the AP trampoline");
    }
    assert!(trampoline_frame.start_address().as_u64() < 0x10_0000);
    let heap_start = Page::containing_address(VirtAddr::new(HEAP_START));
    let heap_end = Page::containing_address(VirtAddr::new(HEAP_START + HEAP_SIZE as u64 - 1));
    let mut heap_pages = 0u64;
    for page in Page::range_inclusive(heap_start, heap_end) {
        let frame = frame_allocator
            .allocate_frame()
            .expect("not enough physical frames for the bounded kernel heap");
        let flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE;
        unsafe { mapper.map_to(page, frame, flags, &mut frame_allocator) }
            .expect("heap virtual page already mapped")
            .flush();
        heap_pages += 1;
    }

    let heap_kernel_only = match mapper.translate(VirtAddr::new(HEAP_START)) {
        TranslateResult::Mapped { flags, .. } => !flags.contains(PageTableFlags::USER_ACCESSIBLE),
        _ => false,
    };
    let guard_unmapped = matches!(
        mapper.translate(VirtAddr::new(GUARD_PAGE)),
        TranslateResult::NotMapped
    );
    let user_level_4 = frame_allocator
        .allocate_frame()
        .expect("no frame for user level-4 page table");
    let user_level_4_ptr =
        (physical_memory_offset + user_level_4.start_address().as_u64()) as *mut PageTable;
    unsafe {
        core::ptr::write_bytes(user_level_4_ptr.cast::<u8>(), 0, 4096);
        for index in 0..512 {
            if index != 0 {
                (&mut *user_level_4_ptr)[index] = (&*active_level_4_ptr)[index].clone();
            }
        }
    }
    let user_level_4_table = unsafe { &mut *user_level_4_ptr };
    let mut user_mapper =
        unsafe { OffsetPageTable::new(user_level_4_table, VirtAddr::new(physical_memory_offset)) };
    let code_page =
        Page::<Size4KiB>::containing_address(VirtAddr::new(crate::process::USER_CODE_START));
    let code_frame = frame_allocator
        .allocate_frame()
        .expect("no user code frame");
    let code_ptr = (physical_memory_offset + code_frame.start_address().as_u64()) as *mut u8;
    unsafe {
        core::ptr::write_bytes(code_ptr, 0xcc, 4096);
        core::ptr::copy_nonoverlapping(user_image.as_ptr(), code_ptr, user_image.len());
        user_mapper
            .map_to(
                code_page,
                code_frame,
                PageTableFlags::PRESENT | PageTableFlags::USER_ACCESSIBLE,
                &mut frame_allocator,
            )
            .expect("user code page collision")
            .ignore();
    }
    let stack_start =
        Page::<Size4KiB>::containing_address(VirtAddr::new(crate::process::USER_STACK_BOTTOM));
    let stack_end =
        Page::<Size4KiB>::containing_address(VirtAddr::new(crate::process::USER_STACK_TOP - 1));
    for page in Page::range_inclusive(stack_start, stack_end) {
        let frame = frame_allocator
            .allocate_frame()
            .expect("no user stack frame");
        let ptr = (physical_memory_offset + frame.start_address().as_u64()) as *mut u8;
        unsafe {
            core::ptr::write_bytes(ptr, 0, 4096);
            user_mapper
                .map_to(
                    page,
                    frame,
                    PageTableFlags::PRESENT
                        | PageTableFlags::WRITABLE
                        | PageTableFlags::USER_ACCESSIBLE
                        | PageTableFlags::NO_EXECUTE,
                    &mut frame_allocator,
                )
                .expect("user stack page collision")
                .ignore();
        }
    }
    let user_code_rx = match user_mapper.translate(VirtAddr::new(crate::process::USER_CODE_START)) {
        TranslateResult::Mapped { flags, .. } => {
            flags.contains(PageTableFlags::USER_ACCESSIBLE)
                && !flags.contains(PageTableFlags::WRITABLE)
                && !flags.contains(PageTableFlags::NO_EXECUTE)
        }
        _ => false,
    };
    let user_stack_nx =
        match user_mapper.translate(VirtAddr::new(crate::process::USER_STACK_BOTTOM)) {
            TranslateResult::Mapped { flags, .. } => {
                flags.contains(PageTableFlags::USER_ACCESSIBLE)
                    && flags.contains(PageTableFlags::WRITABLE)
                    && flags.contains(PageTableFlags::NO_EXECUTE)
            }
            _ => false,
        };
    let kernel_user_inaccessible = match mapper
        .translate(VirtAddr::new(crate::process::USER_CODE_START))
    {
        TranslateResult::Mapped { flags, .. } => !flags.contains(PageTableFlags::USER_ACCESSIBLE),
        TranslateResult::NotMapped | TranslateResult::InvalidFrameAddress(_) => true,
    };
    let user_paging_branch_private =
        user_level_4_table[0].addr() != unsafe { (&*active_level_4_ptr)[0].addr() };
    // Map the SIPI page only into the active kernel root. This deliberately
    // happens after cloning the user root so its low-address page-table branch
    // is private to the process.
    let trampoline_page = Page::<Size4KiB>::containing_address(VirtAddr::new(
        trampoline_frame.start_address().as_u64(),
    ));
    unsafe {
        mapper
            .map_to(
                trampoline_page,
                trampoline_frame,
                PageTableFlags::PRESENT | PageTableFlags::WRITABLE,
                &mut frame_allocator,
            )
            .expect("trampoline identity mapping collision")
            .flush();
    }
    unsafe { ALLOCATOR.init(HEAP_START as usize, HEAP_SIZE) };

    MemorySummary {
        usable_bytes,
        usable_frames,
        heap_pages,
        heap_kernel_only,
        guard_unmapped,
        user_address_space: UserAddressSpace {
            level_4_frame: user_level_4,
        },
        user_code_rx,
        user_stack_nx,
        low_usable_frame,
        trampoline_frame,
        kernel_cr3: level_4_frame.start_address().as_u64(),
        physical_memory_offset,
        kernel_user_inaccessible,
        user_paging_branch_private,
        frame_allocator,
    }
}

impl MemorySummary {
    pub fn allocate_dma_region(&mut self) -> Option<DmaRegion> {
        self.allocate_dma_pages(DmaRegion::PAGED_PAGES, true)
    }

    #[cfg(casulo_native_model_resident)]
    pub fn allocate_resident_model_region(&mut self) -> Option<DmaRegion> {
        self.allocate_dma_pages(DmaRegion::RESIDENT_PAGES, false)
    }

    fn allocate_dma_pages(&mut self, pages: usize, zero: bool) -> Option<DmaRegion> {
        if pages == 0 {
            return None;
        }
        let mut physical_address = self
            .frame_allocator
            .allocate_frame()?
            .start_address()
            .as_u64();
        let mut contiguous_pages = 1usize;
        while contiguous_pages < pages {
            let frame = self.frame_allocator.allocate_frame()?;
            let observed = frame.start_address().as_u64();
            let expected =
                physical_address.checked_add(contiguous_pages as u64 * Size4KiB::SIZE)?;
            if observed == expected {
                contiguous_pages += 1;
            } else {
                // UEFI can split RAM around the PCI aperture. Frames from the
                // abandoned short run remain reserved; continue searching for
                // one bounded run rather than accepting non-contiguous DMA.
                physical_address = observed;
                contiguous_pages = 1;
            }
        }
        let virtual_address = (self.physical_memory_offset + physical_address) as *mut u8;
        let length = pages.checked_mul(Size4KiB::SIZE as usize)?;
        if zero {
            unsafe { core::ptr::write_bytes(virtual_address, 0, length) };
        }
        Some(DmaRegion {
            physical_address,
            virtual_address,
            length,
        })
    }

    /// Construct a fresh low-half user root. The optional private page is
    /// deliberately absent from sibling roots so an actual ring-3 access can
    /// test cross-process isolation rather than only comparing CR3 values.
    pub fn map_probe_process(&mut self, private_page: bool) -> ProbeAddressSpace {
        let active_level_4 = (self.physical_memory_offset + Cr3::read().0.start_address().as_u64())
            as *const PageTable;
        let root = self
            .frame_allocator
            .allocate_frame()
            .expect("no frame for probe process level-4 table");
        let root_ptr =
            (self.physical_memory_offset + root.start_address().as_u64()) as *mut PageTable;
        unsafe {
            core::ptr::write_bytes(root_ptr.cast::<u8>(), 0, 4096);
            for index in 1..512 {
                (&mut *root_ptr)[index] = (&*active_level_4)[index].clone();
            }
        }
        let root_table = unsafe { &mut *root_ptr };
        let mut mapper =
            unsafe { OffsetPageTable::new(root_table, VirtAddr::new(self.physical_memory_offset)) };

        let image = crate::process::user_image();
        assert!(image.len() <= 4096);
        let code_frame = self
            .frame_allocator
            .allocate_frame()
            .expect("no frame for probe process code");
        let code_ptr =
            (self.physical_memory_offset + code_frame.start_address().as_u64()) as *mut u8;
        unsafe {
            core::ptr::write_bytes(code_ptr, 0xcc, 4096);
            core::ptr::copy_nonoverlapping(image.as_ptr(), code_ptr, image.len());
            mapper
                .map_to(
                    Page::containing_address(VirtAddr::new(crate::process::USER_CODE_START)),
                    code_frame,
                    PageTableFlags::PRESENT | PageTableFlags::USER_ACCESSIBLE,
                    &mut self.frame_allocator,
                )
                .expect("probe process code collision")
                .ignore();
        }

        for page in Page::range_inclusive(
            Page::containing_address(VirtAddr::new(crate::process::USER_STACK_BOTTOM)),
            Page::containing_address(VirtAddr::new(crate::process::USER_STACK_TOP - 1)),
        ) {
            let frame = self
                .frame_allocator
                .allocate_frame()
                .expect("no frame for probe process stack");
            let ptr = (self.physical_memory_offset + frame.start_address().as_u64()) as *mut u8;
            unsafe {
                core::ptr::write_bytes(ptr, 0, 4096);
                mapper
                    .map_to(
                        page,
                        frame,
                        PageTableFlags::PRESENT
                            | PageTableFlags::WRITABLE
                            | PageTableFlags::USER_ACCESSIBLE
                            | PageTableFlags::NO_EXECUTE,
                        &mut self.frame_allocator,
                    )
                    .expect("probe process stack collision")
                    .ignore();
            }
        }

        if private_page {
            let frame = self
                .frame_allocator
                .allocate_frame()
                .expect("no frame for process-private probe");
            let ptr = (self.physical_memory_offset + frame.start_address().as_u64()) as *mut u8;
            unsafe {
                core::ptr::write_bytes(ptr, 0, 4096);
                ptr.cast::<u64>()
                    .write_unaligned(crate::process::PRIVATE_PROBE_VALUE);
                mapper
                    .map_to(
                        Page::containing_address(VirtAddr::new(
                            crate::process::PRIVATE_PROBE_START,
                        )),
                        frame,
                        PageTableFlags::PRESENT
                            | PageTableFlags::USER_ACCESSIBLE
                            | PageTableFlags::NO_EXECUTE,
                        &mut self.frame_allocator,
                    )
                    .expect("private probe page collision")
                    .ignore();
            }
        }

        let private_page_mapped = matches!(
            mapper.translate(VirtAddr::new(crate::process::PRIVATE_PROBE_START)),
            TranslateResult::Mapped { flags, .. }
                if flags.contains(PageTableFlags::USER_ACCESSIBLE)
                    && !flags.contains(PageTableFlags::WRITABLE)
                    && flags.contains(PageTableFlags::NO_EXECUTE)
        );
        ProbeAddressSpace {
            address_space: UserAddressSpace {
                level_4_frame: root,
            },
            private_page_mapped,
        }
    }

    /// Create a second, user-only address space for a validated learn payload.
    /// The code is copied from TCAP only after all fail-closed checks pass.
    pub fn map_learn_payload(&mut self, package: &crate::tcap::Package<'_>) -> LearnAddressSpace {
        const CODE: u64 = crate::process::LEARN_CODE_START;
        const DATA: u64 = crate::process::LEARN_DATA_START;
        const STACK_BOTTOM: u64 = crate::process::LEARN_STACK_BOTTOM;
        const STACK_TOP: u64 = crate::process::LEARN_STACK_TOP;
        const CONTEXT_OFFSET: u64 = 0;
        const INPUT_OFFSET: u64 = 128;
        const TARGET_OFFSET: u64 = 640;
        const PARAMETER_OFFSET: u64 = 704;
        const GRADIENT_OFFSET: u64 = 1408;
        const INITIAL_LOSS_OFFSET: u64 = 2064;
        const FINAL_LOSS_OFFSET: u64 = 2072;
        const EXIT_STUB: [u8; 12] = [
            0x48, 0x89, 0xc7, // mov rdi, rax
            0xb8, 0, 0, 0, 0, // mov eax, 0 (EXIT)
            0x0f, 0x05, // syscall
            0x0f, 0x0b, // ud2 if syscall unexpectedly returns
        ];
        const PERMISSION_PROBE: [u8; 32] = [
            0xb8, 2, 0, 0, 0, // mov eax, CLOCK (not granted)
            0x0f, 0x05, // syscall -> -EPERM
            0x48, 0x83, 0xf8, 0xff, // cmp rax, -1
            0x75, 0x08, // jne failure
            0x31, 0xff, // xor edi, edi
            0x31, 0xc0, // xor eax, eax (EXIT)
            0x0f, 0x05, // syscall
            0x0f, 0x0b, // ud2
            0xbf, 98, 0, 0, 0, // failure: mov edi, 98
            0x31, 0xc0, // xor eax, eax
            0x0f, 0x05, // syscall
            0x0f, 0x0b, // ud2
        ];

        assert_eq!(core::mem::size_of::<LearnContextRaw>(), 72);
        let exit_offset = (package.code.bytes.len() + 15) & !15;
        let permission_probe_offset = (exit_offset + EXIT_STUB.len() + 15) & !15;
        let executable_len = permission_probe_offset + PERMISSION_PROBE.len();
        assert!(executable_len <= 3 * 4096);

        let active_level_4 = (self.physical_memory_offset + Cr3::read().0.start_address().as_u64())
            as *const PageTable;
        let user_level_4 = self
            .frame_allocator
            .allocate_frame()
            .expect("no frame for learn level-4 page table");
        let user_level_4_ptr =
            (self.physical_memory_offset + user_level_4.start_address().as_u64()) as *mut PageTable;
        unsafe {
            core::ptr::write_bytes(user_level_4_ptr.cast::<u8>(), 0, 4096);
            for index in 1..512 {
                (&mut *user_level_4_ptr)[index] = (&*active_level_4)[index].clone();
            }
        }
        let user_level_4_table = unsafe { &mut *user_level_4_ptr };
        let mut mapper = unsafe {
            OffsetPageTable::new(
                user_level_4_table,
                VirtAddr::new(self.physical_memory_offset),
            )
        };

        let code_pages = executable_len.div_ceil(4096);
        for page_index in 0..code_pages {
            let frame = self
                .frame_allocator
                .allocate_frame()
                .expect("no learn code frame");
            let frame_ptr =
                (self.physical_memory_offset + frame.start_address().as_u64()) as *mut u8;
            unsafe {
                core::ptr::write_bytes(frame_ptr, 0xcc, 4096);
                let source_start = page_index * 4096;
                if source_start < package.code.bytes.len() {
                    let copy_len = core::cmp::min(4096, package.code.bytes.len() - source_start);
                    core::ptr::copy_nonoverlapping(
                        package.code.bytes.as_ptr().add(source_start),
                        frame_ptr,
                        copy_len,
                    );
                }
                let page_start = page_index * 4096;
                let page_end = page_start + 4096;
                if exit_offset < page_end && exit_offset + EXIT_STUB.len() > page_start {
                    let stub_start = exit_offset.saturating_sub(page_start);
                    let source_start = page_start.saturating_sub(exit_offset);
                    let copy_len =
                        core::cmp::min(EXIT_STUB.len() - source_start, 4096 - stub_start);
                    core::ptr::copy_nonoverlapping(
                        EXIT_STUB.as_ptr().add(source_start),
                        frame_ptr.add(stub_start),
                        copy_len,
                    );
                }
                if permission_probe_offset < page_end
                    && permission_probe_offset + PERMISSION_PROBE.len() > page_start
                {
                    let stub_start = permission_probe_offset.saturating_sub(page_start);
                    let source_start = page_start.saturating_sub(permission_probe_offset);
                    let copy_len =
                        core::cmp::min(PERMISSION_PROBE.len() - source_start, 4096 - stub_start);
                    core::ptr::copy_nonoverlapping(
                        PERMISSION_PROBE.as_ptr().add(source_start),
                        frame_ptr.add(stub_start),
                        copy_len,
                    );
                }
                mapper
                    .map_to(
                        Page::containing_address(VirtAddr::new(CODE + page_start as u64)),
                        frame,
                        PageTableFlags::PRESENT | PageTableFlags::USER_ACCESSIBLE,
                        &mut self.frame_allocator,
                    )
                    .expect("learn code page collision")
                    .ignore();
            }
        }

        let data_frame = self
            .frame_allocator
            .allocate_frame()
            .expect("no learn data frame");
        let data_ptr =
            (self.physical_memory_offset + data_frame.start_address().as_u64()) as *mut u8;
        unsafe {
            core::ptr::write_bytes(data_ptr, 0, 4096);
            core::ptr::copy_nonoverlapping(
                package.canary.inputs_bytes().as_ptr(),
                data_ptr.add(INPUT_OFFSET as usize),
                package.canary.inputs_bytes().len(),
            );
            core::ptr::copy_nonoverlapping(
                package.canary.targets_bytes().as_ptr(),
                data_ptr.add(TARGET_OFFSET as usize),
                package.canary.targets_bytes().len(),
            );
            core::ptr::copy_nonoverlapping(
                package.canary.initial_parameters_bytes().as_ptr(),
                data_ptr.add(PARAMETER_OFFSET as usize),
                package.canary.initial_parameters_bytes().len(),
            );
            data_ptr
                .add(CONTEXT_OFFSET as usize)
                .cast::<LearnContextRaw>()
                .write(LearnContextRaw {
                    inputs: DATA + INPUT_OFFSET,
                    targets: DATA + TARGET_OFFSET,
                    parameters: DATA + PARAMETER_OFFSET,
                    gradients: DATA + GRADIENT_OFFSET,
                    records: package.canary.records,
                    epochs: package.canary.epochs,
                    learning_rate: package.canary.learning_rate,
                    initial_loss: DATA + INITIAL_LOSS_OFFSET,
                    final_loss: DATA + FINAL_LOSS_OFFSET,
                });
            mapper
                .map_to(
                    Page::containing_address(VirtAddr::new(DATA)),
                    data_frame,
                    PageTableFlags::PRESENT
                        | PageTableFlags::WRITABLE
                        | PageTableFlags::USER_ACCESSIBLE
                        | PageTableFlags::NO_EXECUTE,
                    &mut self.frame_allocator,
                )
                .expect("learn data page collision")
                .ignore();
        }

        let stack_start = Page::<Size4KiB>::containing_address(VirtAddr::new(STACK_BOTTOM));
        let stack_end = Page::<Size4KiB>::containing_address(VirtAddr::new(STACK_TOP - 1));
        let mut top_stack_frame = None;
        for page in Page::range_inclusive(stack_start, stack_end) {
            let frame = self
                .frame_allocator
                .allocate_frame()
                .expect("no learn stack frame");
            let ptr = (self.physical_memory_offset + frame.start_address().as_u64()) as *mut u8;
            unsafe {
                core::ptr::write_bytes(ptr, 0, 4096);
                mapper
                    .map_to(
                        page,
                        frame,
                        PageTableFlags::PRESENT
                            | PageTableFlags::WRITABLE
                            | PageTableFlags::USER_ACCESSIBLE
                            | PageTableFlags::NO_EXECUTE,
                        &mut self.frame_allocator,
                    )
                    .expect("learn stack page collision")
                    .ignore();
            }
            top_stack_frame = Some(frame);
        }
        let top_stack_frame = top_stack_frame.expect("learn stack range empty");
        let top_stack_ptr =
            (self.physical_memory_offset + top_stack_frame.start_address().as_u64()) as *mut u8;
        unsafe {
            top_stack_ptr
                .add(4096 - 8)
                .cast::<u64>()
                .write_unaligned(CODE + exit_offset as u64);
        }

        let code_rx = matches!(
            mapper.translate(VirtAddr::new(CODE)),
            TranslateResult::Mapped { flags, .. }
                if flags.contains(PageTableFlags::USER_ACCESSIBLE)
                    && !flags.contains(PageTableFlags::WRITABLE)
                    && !flags.contains(PageTableFlags::NO_EXECUTE)
        );
        let data_rw_nx = matches!(
            mapper.translate(VirtAddr::new(DATA)),
            TranslateResult::Mapped { flags, .. }
                if flags.contains(PageTableFlags::USER_ACCESSIBLE)
                    && flags.contains(PageTableFlags::WRITABLE)
                    && flags.contains(PageTableFlags::NO_EXECUTE)
        );
        let stack_rw_nx = matches!(
            mapper.translate(VirtAddr::new(STACK_BOTTOM)),
            TranslateResult::Mapped { flags, .. }
                if flags.contains(PageTableFlags::USER_ACCESSIBLE)
                    && flags.contains(PageTableFlags::WRITABLE)
                    && flags.contains(PageTableFlags::NO_EXECUTE)
        );
        LearnAddressSpace {
            address_space: UserAddressSpace {
                level_4_frame: user_level_4,
            },
            entry: CODE + package.entry_offset as u64,
            stack_pointer: STACK_TOP - 8,
            context_pointer: DATA + CONTEXT_OFFSET,
            permission_probe_entry: CODE + permission_probe_offset as u64,
            data_physical: data_frame.start_address().as_u64(),
            code_rx,
            data_rw_nx,
            stack_rw_nx,
            mapped_user_bytes: (code_pages as u64 + 1 + 2) * 4096,
        }
    }

    pub fn read_learn_f64(&self, mapped: LearnAddressSpace, offset: usize) -> f64 {
        let pointer = (self.physical_memory_offset + mapped.data_physical) as *const u8;
        unsafe { pointer.add(offset).cast::<f64>().read_unaligned() }
    }
}
