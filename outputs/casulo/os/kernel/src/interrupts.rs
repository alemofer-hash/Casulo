use crate::memory::GUARD_PAGE;
use crate::once::Once;
use crate::serial::Serial;
use core::fmt::Write;
use core::sync::atomic::{AtomicU64, Ordering};
use x86_64::VirtAddr;
use x86_64::instructions::segmentation::{CS, DS, ES, SS, Segment};
use x86_64::instructions::tables::load_tss;
use x86_64::instructions::{hlt, interrupts as cpu_interrupts, port::Port};
use x86_64::registers::control::Cr2;
use x86_64::structures::gdt::{Descriptor, GlobalDescriptorTable, SegmentSelector};
use x86_64::structures::idt::{InterruptDescriptorTable, InterruptStackFrame, PageFaultErrorCode};
use x86_64::structures::tss::TaskStateSegment;

const DOUBLE_FAULT_IST_INDEX: u16 = 0;
const TIMER_VECTOR: u8 = 32;
const PIT_FREQUENCY_HZ: u64 = 100;
const PIT_DIVISOR: u16 = 11_932;

#[repr(align(16))]
struct KernelStack([u8; 4096 * 5]);

static mut DOUBLE_FAULT_STACK: KernelStack = KernelStack([0; 4096 * 5]);
static mut RING0_INTERRUPT_STACK: KernelStack = KernelStack([0; 4096 * 5]);
static TSS: Once<TaskStateSegment> = Once::new();
static GDT: Once<(GlobalDescriptorTable, Selectors)> = Once::new();
static IDT: Once<InterruptDescriptorTable> = Once::new();
static TIMER_TICKS: AtomicU64 = AtomicU64::new(0);
static EXPECTED_FAULT: AtomicU64 = AtomicU64::new(0);
static RECOVERY_RIP: AtomicU64 = AtomicU64::new(0);
static CONTAINED_FAULTS: AtomicU64 = AtomicU64::new(0);
static EXPECTED_USER_FAULT: AtomicU64 = AtomicU64::new(0);
static USER_FAULT_RECOVERY_RIP: AtomicU64 = AtomicU64::new(0);
static CONTAINED_USER_FAULTS: AtomicU64 = AtomicU64::new(0);
static USER_WATCHDOG_START: AtomicU64 = AtomicU64::new(0);
static USER_WATCHDOG_BUDGET: AtomicU64 = AtomicU64::new(0);
static USER_WATCHDOG_RECOVERY_RIP: AtomicU64 = AtomicU64::new(0);
static USER_WATCHDOG_PREEMPTIONS: AtomicU64 = AtomicU64::new(0);
static USER_WATCHDOG_ELAPSED: AtomicU64 = AtomicU64::new(0);

struct Selectors {
    kernel_code: SegmentSelector,
    kernel_data: SegmentSelector,
    user_data: SegmentSelector,
    user_code: SegmentSelector,
    tss: SegmentSelector,
}

pub struct InterruptSummary {
    pub timer_ticks: u64,
    pub timer_hz: u64,
    pub contained_faults: u64,
    pub watchdog_passed: bool,
}

pub struct Watchdog {
    last_progress: u64,
    deadline_ticks: u64,
}

impl Watchdog {
    pub const fn armed(now: u64, deadline_ticks: u64) -> Self {
        Self {
            last_progress: now,
            deadline_ticks,
        }
    }

    pub fn feed(&mut self, now: u64) {
        self.last_progress = now;
    }

    pub fn expired(&self, now: u64) -> bool {
        now.saturating_sub(self.last_progress) > self.deadline_ticks
    }
}

fn init_gdt() {
    let tss = TSS.call_once(|| {
        let mut tss = TaskStateSegment::new();
        let stack_start = unsafe { core::ptr::addr_of!(DOUBLE_FAULT_STACK.0) as *const u8 as u64 };
        tss.interrupt_stack_table[DOUBLE_FAULT_IST_INDEX as usize] =
            VirtAddr::new(stack_start + 4096 * 5);
        let ring0_start =
            unsafe { core::ptr::addr_of!(RING0_INTERRUPT_STACK.0) as *const u8 as u64 };
        tss.privilege_stack_table[0] = VirtAddr::new(ring0_start + 4096 * 5);
        tss
    });
    let (gdt, selectors) = GDT.call_once(|| {
        let mut gdt = GlobalDescriptorTable::new();
        let selectors = Selectors {
            kernel_code: gdt.append(Descriptor::kernel_code_segment()),
            kernel_data: gdt.append(Descriptor::kernel_data_segment()),
            user_data: gdt.append(Descriptor::user_data_segment()),
            user_code: gdt.append(Descriptor::user_code_segment()),
            tss: gdt.append(Descriptor::tss_segment(tss)),
        };
        (gdt, selectors)
    });
    gdt.load();
    unsafe {
        CS::set_reg(selectors.kernel_code);
        SS::set_reg(selectors.kernel_data);
        DS::set_reg(selectors.kernel_data);
        ES::set_reg(selectors.kernel_data);
        load_tss(selectors.tss);
    }
}

#[derive(Clone, Copy)]
pub struct AbiSelectors {
    pub kernel_code: SegmentSelector,
    pub kernel_data: SegmentSelector,
    pub user_data: SegmentSelector,
    pub user_code: SegmentSelector,
}

pub fn selectors() -> AbiSelectors {
    let (_, value) = GDT.get().expect("GDT must be initialized before syscalls");
    AbiSelectors {
        kernel_code: value.kernel_code,
        kernel_data: value.kernel_data,
        user_data: SegmentSelector(value.user_data.0 | 3),
        user_code: SegmentSelector(value.user_code.0 | 3),
    }
}

pub fn timer_ticks() -> u64 {
    TIMER_TICKS.load(Ordering::Acquire)
}

pub fn arm_user_fault(address: u64, recovery_rip: u64) {
    EXPECTED_USER_FAULT.store(address, Ordering::Release);
    USER_FAULT_RECOVERY_RIP.store(recovery_rip, Ordering::Release);
}

pub fn disarm_user_fault() {
    EXPECTED_USER_FAULT.store(0, Ordering::Release);
    USER_FAULT_RECOVERY_RIP.store(0, Ordering::Release);
}

pub fn contained_user_faults() -> u64 {
    CONTAINED_USER_FAULTS.load(Ordering::Acquire)
}

pub fn arm_user_watchdog(budget_ticks: u64, recovery_rip: u64) {
    assert!(budget_ticks > 0);
    USER_WATCHDOG_ELAPSED.store(0, Ordering::Release);
    USER_WATCHDOG_START.store(timer_ticks(), Ordering::Release);
    USER_WATCHDOG_RECOVERY_RIP.store(recovery_rip, Ordering::Release);
    USER_WATCHDOG_BUDGET.store(budget_ticks, Ordering::Release);
}

pub fn disarm_user_watchdog() {
    USER_WATCHDOG_BUDGET.store(0, Ordering::Release);
    USER_WATCHDOG_RECOVERY_RIP.store(0, Ordering::Release);
}

pub fn user_watchdog_preemptions() -> u64 {
    USER_WATCHDOG_PREEMPTIONS.load(Ordering::Acquire)
}

pub fn user_watchdog_elapsed_ticks() -> u64 {
    USER_WATCHDOG_ELAPSED.load(Ordering::Acquire)
}

fn init_idt() {
    let idt = IDT.call_once(|| {
        let mut idt = InterruptDescriptorTable::new();
        idt.breakpoint.set_handler_fn(breakpoint_handler);
        idt.page_fault.set_handler_fn(page_fault_handler);
        unsafe {
            idt.double_fault
                .set_handler_fn(double_fault_handler)
                .set_stack_index(DOUBLE_FAULT_IST_INDEX);
        }
        idt[TIMER_VECTOR].set_handler_fn(timer_handler);
        idt
    });
    idt.load();
}

unsafe fn init_legacy_timer() {
    cpu_interrupts::disable();
    unsafe {
        // Remap 8259 PICs to 32..47, preserving only IRQ0 (PIT) on the master.
        let mut master_command: Port<u8> = Port::new(0x20);
        let mut master_data: Port<u8> = Port::new(0x21);
        let mut slave_command: Port<u8> = Port::new(0xa0);
        let mut slave_data: Port<u8> = Port::new(0xa1);
        master_command.write(0x11);
        slave_command.write(0x11);
        master_data.write(0x20);
        slave_data.write(0x28);
        master_data.write(0x04);
        slave_data.write(0x02);
        master_data.write(0x01);
        slave_data.write(0x01);
        master_data.write(0xfe);
        slave_data.write(0xff);

        let mut pit_command: Port<u8> = Port::new(0x43);
        let mut pit_channel0: Port<u8> = Port::new(0x40);
        pit_command.write(0x36);
        pit_channel0.write((PIT_DIVISOR & 0xff) as u8);
        pit_channel0.write((PIT_DIVISOR >> 8) as u8);
    }
    cpu_interrupts::enable();
}

pub fn initialize_and_self_test() -> InterruptSummary {
    init_gdt();
    init_idt();
    x86_64::instructions::interrupts::int3();
    unsafe { init_legacy_timer() };

    let initial = TIMER_TICKS.load(Ordering::Acquire);
    let target = initial + 3;
    let tsc_start = unsafe { core::arch::x86_64::_rdtsc() };
    let tsc_budget = 8_000_000_000u64;
    while TIMER_TICKS.load(Ordering::Acquire) < target {
        if unsafe { core::arch::x86_64::_rdtsc() }.wrapping_sub(tsc_start) > tsc_budget {
            fatal("WATCHDOG_TIMER_STALLED");
        }
        core::hint::spin_loop();
    }

    let mut watchdog = Watchdog::armed(initial, 4);
    watchdog.feed(TIMER_TICKS.load(Ordering::Acquire));
    let watchdog_passed = !watchdog.expired(TIMER_TICKS.load(Ordering::Acquire) + 4)
        && Watchdog::armed(10, 2).expired(13);

    assert_eq!(EXPECTED_FAULT.load(Ordering::Acquire), 0);
    assert_eq!(RECOVERY_RIP.load(Ordering::Acquire), 0);
    RECOVERY_RIP.store(
        casulo_guard_recovery as *const () as usize as u64,
        Ordering::Release,
    );
    EXPECTED_FAULT.store(GUARD_PAGE, Ordering::Release);
    unsafe { trigger_guard_page_fault(GUARD_PAGE) };
    let contained_faults = CONTAINED_FAULTS.load(Ordering::Acquire);

    InterruptSummary {
        timer_ticks: TIMER_TICKS.load(Ordering::Acquire),
        timer_hz: PIT_FREQUENCY_HZ,
        contained_faults,
        watchdog_passed,
    }
}

#[inline(never)]
unsafe fn trigger_guard_page_fault(address: u64) {
    unsafe {
        core::arch::asm!(
            "mov rax, qword ptr [{address}]",
            address = in(reg) address,
            out("rax") _,
            options(nostack, readonly)
        );
    }
}

#[unsafe(no_mangle)]
#[inline(never)]
extern "C" fn casulo_guard_recovery() {}

extern "x86-interrupt" fn breakpoint_handler(_frame: InterruptStackFrame) {
    // Intentional software exception used to prove the IDT is live.
}

extern "x86-interrupt" fn timer_handler(mut frame: InterruptStackFrame) {
    let now = TIMER_TICKS.fetch_add(1, Ordering::AcqRel) + 1;
    let budget = USER_WATCHDOG_BUDGET.load(Ordering::Acquire);
    let recovery = USER_WATCHDOG_RECOVERY_RIP.load(Ordering::Acquire);
    let interrupted_user = frame.code_segment.0 & 3 == 3;
    if interrupted_user
        && budget != 0
        && recovery != 0
        && now.saturating_sub(USER_WATCHDOG_START.load(Ordering::Acquire)) >= budget
    {
        USER_WATCHDOG_ELAPSED.store(
            now.saturating_sub(USER_WATCHDOG_START.load(Ordering::Acquire)),
            Ordering::Release,
        );
        USER_WATCHDOG_BUDGET.store(0, Ordering::Release);
        USER_WATCHDOG_RECOVERY_RIP.store(0, Ordering::Release);
        USER_WATCHDOG_PREEMPTIONS.fetch_add(1, Ordering::AcqRel);
        unsafe {
            frame
                .as_mut()
                .update(|value| value.instruction_pointer = VirtAddr::new(recovery));
        }
    }
    unsafe {
        let mut master_command: Port<u8> = Port::new(0x20);
        master_command.write(0x20);
    }
}

extern "x86-interrupt" fn page_fault_handler(
    mut frame: InterruptStackFrame,
    error_code: PageFaultErrorCode,
) {
    let fault_address = Cr2::read_raw();
    let interrupted_user = frame.code_segment.0 & 3 == 3;
    let expected_user = EXPECTED_USER_FAULT.load(Ordering::Acquire);
    let user_recovery = USER_FAULT_RECOVERY_RIP.load(Ordering::Acquire);
    if interrupted_user
        && fault_address == expected_user
        && expected_user != 0
        && user_recovery != 0
    {
        disarm_user_fault();
        CONTAINED_USER_FAULTS.fetch_add(1, Ordering::AcqRel);
        unsafe {
            frame
                .as_mut()
                .update(|value| value.instruction_pointer = VirtAddr::new(user_recovery));
        }
        return;
    }
    let expected = EXPECTED_FAULT.load(Ordering::Acquire);
    let recovery = RECOVERY_RIP.load(Ordering::Acquire);
    if fault_address == expected && expected != 0 && recovery != 0 {
        EXPECTED_FAULT.store(0, Ordering::Release);
        RECOVERY_RIP.store(0, Ordering::Release);
        CONTAINED_FAULTS.fetch_add(1, Ordering::Release);
        unsafe {
            frame
                .as_mut()
                .update(|value| value.instruction_pointer = VirtAddr::new(recovery));
        }
        return;
    }
    let mut serial = Serial::init();
    let _ = writeln!(
        serial,
        "UNCONTAINED_PAGE_FAULT addr={:#x} error={:?}",
        fault_address, error_code
    );
    fatal("UNCONTAINED_PAGE_FAULT");
}

extern "x86-interrupt" fn double_fault_handler(_frame: InterruptStackFrame, error_code: u64) -> ! {
    let mut serial = Serial::init();
    let _ = writeln!(serial, "DOUBLE_FAULT error={error_code}");
    fatal("DOUBLE_FAULT")
}

fn fatal(message: &str) -> ! {
    cpu_interrupts::disable();
    let mut serial = Serial::init();
    let _ = writeln!(serial, "CASULO_KERNEL_FATAL={message}");
    loop {
        hlt();
    }
}
