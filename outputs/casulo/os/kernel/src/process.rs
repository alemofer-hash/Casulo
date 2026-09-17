//! Bounded ring-3 execution and trap boundary for Research Preview 0.1.
//!
//! The byte program is copied into a user-only RX page.  It exercises the
//! `syscall`/`sysretq` path and returns to the suspended kernel stack through
//! the EXIT syscall.  This is deliberately a single-process proof, not a
//! general process manager.

use crate::interrupts;
use crate::memory::UserAddressSpace;
use crate::serial::Serial;
use core::arch::global_asm;
use core::arch::{asm, x86_64::__cpuid};
use core::sync::atomic::{AtomicBool, AtomicI64, AtomicU8, AtomicU64, Ordering};
use x86_64::VirtAddr;
use x86_64::registers::control::{Cr3, Cr3Flags};
use x86_64::registers::model_specific::{Efer, EferFlags, LStar, SFMask, Star};
use x86_64::registers::rflags::RFlags;

pub const USER_CODE_START: u64 = 0x0040_0000;
pub const USER_STACK_BOTTOM: u64 = 0x007f_e000;
pub const USER_STACK_TOP: u64 = 0x0080_0000;
pub const LEARN_CODE_START: u64 = 0x0100_0000;
pub const LEARN_DATA_START: u64 = 0x0200_0000;
pub const LEARN_STACK_BOTTOM: u64 = 0x02ff_e000;
pub const LEARN_STACK_TOP: u64 = 0x0300_0000;
pub const PRIVATE_PROBE_START: u64 = 0x0060_0000;
pub const PRIVATE_PROBE_VALUE: u64 = 0x4341_5355_4c4f_5031;

const ENOSYS: i64 = -38;
const EFAULT: i64 = -14;
const EPERM: i64 = -1;
const EINVAL: i64 = -22;
const MAX_CONSOLE_WRITE: usize = 256;

#[unsafe(no_mangle)]
static mut CASULO_USER_RSP: u64 = 0;
#[unsafe(no_mangle)]
static mut CASULO_USER_RIP: u64 = 0;
#[unsafe(no_mangle)]
static mut CASULO_KERNEL_RSP: u64 = 0;
#[unsafe(no_mangle)]
static mut CASULO_KERNEL_CR3: u64 = 0;

#[allow(dead_code)]
#[repr(align(16))]
struct SyscallStack([u8; 16 * 1024]);

#[unsafe(no_mangle)]
static mut CASULO_SYSCALL_STACK: SyscallStack = SyscallStack([0; 16 * 1024]);

static EXIT_REQUESTED: AtomicBool = AtomicBool::new(false);
static EXIT_STATUS: AtomicI64 = AtomicI64::new(-1);
static SYSCALL_COUNT: AtomicU64 = AtomicU64::new(0);
static CONSOLE_BYTES: AtomicU64 = AtomicU64::new(0);
static UNKNOWN_REJECTED: AtomicBool = AtomicBool::new(false);
static IPC_SENDS: AtomicU64 = AtomicU64::new(0);
static IPC_RECVS: AtomicU64 = AtomicU64::new(0);
static TRACE_EVENTS: AtomicU64 = AtomicU64::new(0);
static PERMISSION_MASK: AtomicU64 = AtomicU64::new(0);
static DENIED_SYSCALLS: AtomicU64 = AtomicU64::new(0);
static PERMISSION_AUDIT_EVENTS: AtomicU64 = AtomicU64::new(0);
static YIELD_KERNEL_RETURNS: AtomicU64 = AtomicU64::new(0);
static NEURAL_MODEL_ASSERTS: AtomicU64 = AtomicU64::new(0);
static NEURAL_PRIMITIVE_CALLS: AtomicU64 = AtomicU64::new(0);
static NEURAL_TOKENS_EMITTED: AtomicU64 = AtomicU64::new(0);
static NEURAL_LAST_TOKEN: AtomicU64 = AtomicU64::new(0);
static NEURAL_RECEIPT_ACCUMULATOR: AtomicU64 = AtomicU64::new(0);
static MAILBOX_LEN: AtomicU64 = AtomicU64::new(0);
static mut MAILBOX: [u8; 64] = [0; 64];

global_asm!(
    r#"
    .global casulo_syscall_entry
    .type casulo_syscall_entry,@function
casulo_syscall_entry:
    cld
    mov [rip + CASULO_USER_RSP], rsp
    mov [rip + CASULO_USER_RIP], rcx
    lea rsp, [rip + CASULO_SYSCALL_STACK + 16384]
    push rcx
    push r11
    push rbx
    push r12
    mov rbx, rdi
    mov r12, rsi
    mov rdi, rax
    mov rsi, rbx
    mov rdx, r12
    call casulo_syscall_dispatch
    pop r12
    pop rbx
    pop r11
    pop rcx
    cmp byte ptr [rip + CASULO_TRAP_ACTION], 0
    jne casulo_return_to_kernel
    mov rsp, [rip + CASULO_USER_RSP]
    sysretq

casulo_return_to_kernel:
    mov rax, [rip + CASULO_KERNEL_CR3]
    mov cr3, rax
    mov rsp, [rip + CASULO_KERNEL_RSP]
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbx
    pop rbp
    ret

    .global casulo_enter_user
    .type casulo_enter_user,@function
casulo_enter_user:
    push rbp
    push rbx
    push r12
    push r13
    push r14
    push r15
    mov [rip + CASULO_KERNEL_RSP], rsp
    mov rax, cr3
    mov [rip + CASULO_KERNEL_CR3], rax
    mov cr3, rdi
    mov rdi, rcx
    push 0x1b
    push rdx
    push 0x202
    push 0x23
    push rsi
    iretq

    .section .rodata.casulo_user,"a",@progbits
    .global casulo_user_image_start
casulo_user_image_start:
casulo_user_message:
    .ascii "RING3_CONSOLE_WRITE=PASS\n"
casulo_user_message_end:
    .balign 64
    .global casulo_user_entry
casulo_user_entry:
    mov rax, 2
    syscall
    mov r12, rax
    mov rax, 99
    syscall
    cmp rax, -38
    jne casulo_user_fail
    movabs rdi, 0x400000
    mov rsi, 25
    mov rax, 1
    syscall
    cmp rax, 25
    jne casulo_user_fail
    movabs rdi, 0x400000
    mov rsi, 25
    mov rax, 4
    syscall
    cmp rax, 25
    jne casulo_user_fail
    lea rdi, [rsp - 64]
    mov rsi, 64
    mov rax, 5
    syscall
    cmp rax, 25
    jne casulo_user_fail
    cmp byte ptr [rsp - 64], 0x52
    jne casulo_user_fail
    movabs rdi, 0x400000
    mov rsi, 25
    mov rax, 6
    syscall
    cmp rax, 25
    jne casulo_user_fail
    mov rax, 3
    syscall
    mov rax, 0
    mov rdi, 42
    syscall
    ud2
casulo_user_fail:
    mov rax, 0
    mov rdi, 99
    syscall
    ud2

    .balign 16
    .global casulo_yield_slice_entry
casulo_yield_slice_entry:
    mov rax, 3
    syscall
    mov rax, 0
    mov rdi, 97
    syscall
    ud2

    .balign 16
    .global casulo_fault_probe_entry
casulo_fault_probe_entry:
    movabs rax, 0x600000
    mov rax, qword ptr [rax]
    mov rax, 0
    mov rdi, 96
    syscall
    ud2

    .balign 16
    .global casulo_private_probe_entry
casulo_private_probe_entry:
    movabs rax, 0x600000
    mov rax, qword ptr [rax]
    movabs rcx, 0x434153554c4f5031
    cmp rax, rcx
    jne casulo_private_probe_fail
    xor rdi, rdi
    xor rax, rax
    syscall
    ud2
casulo_private_probe_fail:
    mov rdi, 95
    xor rax, rax
    syscall
    ud2

    .balign 16
    .global casulo_non_yielding_entry
casulo_non_yielding_entry:
    pause
    jmp casulo_non_yielding_entry

    .balign 16
casulo_neural_descriptor:
    .ascii "CSNABI01"
    .long 1
    .long 0
    .rept 32
    .byte 0x5a
    .endr
    .long 4096
    .long 1
    .quad 0

    .balign 16
    .global casulo_neural_abi_entry
casulo_neural_abi_entry:
    lea rdi, [rip + casulo_neural_descriptor]
    mov rsi, 64
    mov rax, 7
    syscall
    test rax, rax
    jne casulo_neural_abi_fail

    movabs rax, 0x0004000300020001
    mov qword ptr [rsp - 32], rax
    movabs rax, 0x0008000700060005
    mov qword ptr [rsp - 24], rax
    mov qword ptr [rsp - 16], 0
    lea rdi, [rsp - 32]
    mov rsi, 24
    mov rax, 8
    syscall
    cmp rax, 70
    jne casulo_neural_abi_fail
    cmp dword ptr [rsp - 16], 70
    jne casulo_neural_abi_fail

    mov rdi, 42
    mov rsi, 0xc451
    mov rax, 9
    syscall
    cmp rax, 42
    jne casulo_neural_abi_fail
    xor rdi, rdi
    xor rax, rax
    syscall
    ud2
casulo_neural_abi_fail:
    mov rdi, 93
    xor rax, rax
    syscall
    ud2

    .balign 16
    .global casulo_neural_abi_permission_entry
casulo_neural_abi_permission_entry:
    lea rdi, [rip + casulo_neural_descriptor]
    mov rsi, 64
    mov rax, 7
    syscall
    cmp rax, -1
    jne casulo_neural_permission_fail
    xor rdi, rdi
    xor rax, rax
    syscall
    ud2
casulo_neural_permission_fail:
    mov rdi, 92
    xor rax, rax
    syscall
    ud2

    .balign 16
    .global casulo_fault_exit_entry
casulo_fault_exit_entry:
    mov rdi, 125
    xor rax, rax
    syscall
    ud2

    .balign 16
    .global casulo_watchdog_exit_entry
casulo_watchdog_exit_entry:
    mov rdi, 124
    xor rax, rax
    syscall
    ud2
    .global casulo_user_image_end
casulo_user_image_end:
    .previous
"#
);

unsafe extern "C" {
    fn casulo_syscall_entry();
    fn casulo_enter_user(cr3: u64, rip: u64, rsp: u64, context: u64);
    static casulo_user_image_start: u8;
    static casulo_user_image_end: u8;
    static casulo_user_entry: u8;
    static casulo_yield_slice_entry: u8;
    static casulo_fault_probe_entry: u8;
    static casulo_private_probe_entry: u8;
    static casulo_non_yielding_entry: u8;
    static casulo_neural_abi_entry: u8;
    static casulo_neural_abi_permission_entry: u8;
    static casulo_fault_exit_entry: u8;
    static casulo_watchdog_exit_entry: u8;
}

// The assembly path reads one byte only. This alias keeps the ABI explicit and
// avoids depending on AtomicBool's Rust symbol layout in handwritten assembly.
#[unsafe(no_mangle)]
static CASULO_TRAP_ACTION: AtomicU8 = AtomicU8::new(0);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum UserTrap {
    None = 0,
    Exit = 1,
    Yield = 2,
}

pub struct ProcessSummary {
    pub exit_status: i64,
    pub syscall_count: u64,
    pub console_bytes: u64,
    pub unknown_rejected: bool,
    pub separate_cr3: bool,
    pub ipc_roundtrip: bool,
    pub trace_events: u64,
    pub permission_mask: u64,
    pub denied_syscalls: u64,
    pub permission_audit_events: u64,
    pub yield_kernel_returns: u64,
    pub neural_model_asserts: u64,
    pub neural_primitive_calls: u64,
    pub neural_tokens_emitted: u64,
    pub neural_last_token: u64,
    pub neural_receipt_accumulator: u64,
    pub trap: UserTrap,
}

pub fn user_image() -> &'static [u8] {
    let start = core::ptr::addr_of!(casulo_user_image_start) as usize;
    let end = core::ptr::addr_of!(casulo_user_image_end) as usize;
    assert!(end > start && end - start <= 4096);
    unsafe { core::slice::from_raw_parts(start as *const u8, end - start) }
}

pub fn initialize_syscall_abi() {
    let selectors = interrupts::selectors();
    Star::write(
        selectors.user_code,
        selectors.user_data,
        selectors.kernel_code,
        selectors.kernel_data,
    )
    .expect("GDT selector order violates syscall/sysret ABI");
    LStar::write(VirtAddr::new(casulo_syscall_entry as *const () as u64));
    SFMask::write(RFlags::INTERRUPT_FLAG | RFlags::DIRECTION_FLAG);
    unsafe {
        Efer::update(|flags| flags.insert(EferFlags::SYSTEM_CALL_EXTENSIONS));
    }
}

/// Arm the architectural SSE2 state required by the frozen float64 payload.
/// Returns false on a CPU that cannot uphold that ABI.
pub fn initialize_sse2() -> bool {
    let supported = (__cpuid(1).edx & (1 << 26)) != 0;
    if !supported {
        return false;
    }
    unsafe {
        let mut cr0: u64;
        asm!("mov {}, cr0", out(reg) cr0, options(nostack, preserves_flags));
        cr0 &= !((1 << 2) | (1 << 3)); // EM=0, TS=0
        cr0 |= (1 << 1) | (1 << 5); // MP=1, NE=1
        asm!("mov cr0, {}", in(reg) cr0, options(nostack, preserves_flags));
        let mut cr4: u64;
        asm!("mov {}, cr4", out(reg) cr4, options(nostack, preserves_flags));
        cr4 |= (1 << 9) | (1 << 10); // OSFXSR, OSXMMEXCPT
        asm!("mov cr4, {}", in(reg) cr4, options(nostack, preserves_flags));
        let mxcsr: u32 = 0x1f80; // round-to-nearest, all exceptions masked
        asm!("ldmxcsr [{}]", in(reg) &mxcsr, options(nostack, preserves_flags, readonly));
        let mut verified_cr0: u64;
        let mut verified_cr4: u64;
        asm!("mov {}, cr0", out(reg) verified_cr0, options(nostack, preserves_flags));
        asm!("mov {}, cr4", out(reg) verified_cr4, options(nostack, preserves_flags));
        verified_cr0 & ((1 << 2) | (1 << 3)) == 0
            && verified_cr0 & (1 << 1) != 0
            && verified_cr4 & ((1 << 9) | (1 << 10)) == ((1 << 9) | (1 << 10))
    }
}

pub fn run(address_space: UserAddressSpace) -> ProcessSummary {
    reset_accounting();
    PERMISSION_MASK.store(0x7f, Ordering::Release);
    let (kernel_frame, _) = Cr3::read();
    let separate_cr3 = kernel_frame != address_space.level_4_frame;
    let cr3 = address_space.level_4_frame.start_address().as_u64() | Cr3Flags::empty().bits();
    let entry_offset = core::ptr::addr_of!(casulo_user_entry) as u64
        - core::ptr::addr_of!(casulo_user_image_start) as u64;
    let mut rip = USER_CODE_START + entry_offset;
    let mut rsp = USER_STACK_TOP - 16;
    loop {
        unsafe { casulo_enter_user(cr3, rip, rsp, 0) };
        match trap_action() {
            UserTrap::Yield => {
                YIELD_KERNEL_RETURNS.fetch_add(1, Ordering::AcqRel);
                rip = unsafe { CASULO_USER_RIP };
                rsp = unsafe { CASULO_USER_RSP };
                CASULO_TRAP_ACTION.store(UserTrap::None as u8, Ordering::Release);
            }
            UserTrap::Exit => break,
            UserTrap::None => break,
        }
    }
    summary(separate_cr3)
}

/// Execute one real ring-3 slice. Its YIELD syscall must trap back to the
/// bounded kernel task manager; the user continuation is deliberately retired.
pub fn run_yield_slice(address_space: UserAddressSpace) -> ProcessSummary {
    run_entry(
        address_space,
        symbol_offset(core::ptr::addr_of!(casulo_yield_slice_entry)),
        0x09,
    )
}

pub fn run_private_probe(address_space: UserAddressSpace) -> ProcessSummary {
    run_entry(
        address_space,
        symbol_offset(core::ptr::addr_of!(casulo_private_probe_entry)),
        0x01,
    )
}

pub fn run_cross_space_fault_probe(address_space: UserAddressSpace) -> ProcessSummary {
    reset_accounting();
    PERMISSION_MASK.store(0x01, Ordering::Release);
    let recovery = USER_CODE_START + symbol_offset(core::ptr::addr_of!(casulo_fault_exit_entry));
    crate::interrupts::arm_user_fault(PRIVATE_PROBE_START, recovery);
    let summary = run_entry_without_reset(
        address_space,
        symbol_offset(core::ptr::addr_of!(casulo_fault_probe_entry)),
    );
    crate::interrupts::disarm_user_fault();
    summary
}

pub fn run_non_yielding_watchdog(
    address_space: UserAddressSpace,
    budget_ticks: u64,
) -> ProcessSummary {
    reset_accounting();
    PERMISSION_MASK.store(0x01, Ordering::Release);
    let recovery = USER_CODE_START + symbol_offset(core::ptr::addr_of!(casulo_watchdog_exit_entry));
    crate::interrupts::arm_user_watchdog(budget_ticks, recovery);
    let summary = run_entry_without_reset(
        address_space,
        symbol_offset(core::ptr::addr_of!(casulo_non_yielding_entry)),
    );
    crate::interrupts::disarm_user_watchdog();
    summary
}

/// Exercise the minimal neural primitive ABI from a real ring-3 process.
///
/// This validates capability checks, a content-addressed model descriptor, a
/// bounded integer dot-product primitive, and receipt-backed token emission.
/// It deliberately does not claim to load a GGUF or execute neural inference.
pub fn run_neural_abi(address_space: UserAddressSpace) -> ProcessSummary {
    run_entry(
        address_space,
        symbol_offset(core::ptr::addr_of!(casulo_neural_abi_entry)),
        0x0381, // EXIT + MODEL_ASSERT + PRIMITIVE + TOKEN_EMIT
    )
}

pub fn run_neural_abi_permission_probe(address_space: UserAddressSpace) -> ProcessSummary {
    run_entry(
        address_space,
        symbol_offset(core::ptr::addr_of!(casulo_neural_abi_permission_entry)),
        0x0001, // EXIT only; MODEL_ASSERT must fail closed.
    )
}

fn run_entry(
    address_space: UserAddressSpace,
    entry_offset: u64,
    permission_mask: u64,
) -> ProcessSummary {
    reset_accounting();
    PERMISSION_MASK.store(permission_mask, Ordering::Release);
    run_entry_without_reset(address_space, entry_offset)
}

fn run_entry_without_reset(address_space: UserAddressSpace, entry_offset: u64) -> ProcessSummary {
    let (kernel_frame, _) = Cr3::read();
    let separate_cr3 = kernel_frame != address_space.level_4_frame;
    let cr3 = address_space.level_4_frame.start_address().as_u64() | Cr3Flags::empty().bits();
    unsafe { casulo_enter_user(cr3, USER_CODE_START + entry_offset, USER_STACK_TOP - 16, 0) };
    if trap_action() == UserTrap::Yield {
        YIELD_KERNEL_RETURNS.fetch_add(1, Ordering::AcqRel);
    }
    summary(separate_cr3)
}

fn symbol_offset(symbol: *const u8) -> u64 {
    symbol as u64 - core::ptr::addr_of!(casulo_user_image_start) as u64
}

fn trap_action() -> UserTrap {
    match CASULO_TRAP_ACTION.load(Ordering::Acquire) {
        1 => UserTrap::Exit,
        2 => UserTrap::Yield,
        _ => UserTrap::None,
    }
}

pub fn run_learn(mapped: crate::memory::LearnAddressSpace) -> ProcessSummary {
    reset_accounting();
    PERMISSION_MASK.store(0x03, Ordering::Release); // system EXIT plus declared console
    let (kernel_frame, _) = Cr3::read();
    let separate_cr3 = kernel_frame != mapped.address_space.level_4_frame;
    let cr3 =
        mapped.address_space.level_4_frame.start_address().as_u64() | Cr3Flags::empty().bits();
    unsafe {
        casulo_enter_user(
            cr3,
            mapped.entry,
            mapped.stack_pointer,
            mapped.context_pointer,
        )
    };
    summary(separate_cr3)
}

pub fn run_learn_permission_probe(mapped: crate::memory::LearnAddressSpace) -> ProcessSummary {
    reset_accounting();
    PERMISSION_MASK.store(0x03, Ordering::Release);
    let (kernel_frame, _) = Cr3::read();
    let separate_cr3 = kernel_frame != mapped.address_space.level_4_frame;
    let cr3 =
        mapped.address_space.level_4_frame.start_address().as_u64() | Cr3Flags::empty().bits();
    unsafe {
        casulo_enter_user(
            cr3,
            mapped.permission_probe_entry,
            mapped.stack_pointer,
            mapped.context_pointer,
        )
    };
    summary(separate_cr3)
}

fn reset_accounting() {
    EXIT_REQUESTED.store(false, Ordering::Release);
    CASULO_TRAP_ACTION.store(UserTrap::None as u8, Ordering::Release);
    EXIT_STATUS.store(-1, Ordering::Release);
    SYSCALL_COUNT.store(0, Ordering::Release);
    CONSOLE_BYTES.store(0, Ordering::Release);
    UNKNOWN_REJECTED.store(false, Ordering::Release);
    IPC_SENDS.store(0, Ordering::Release);
    IPC_RECVS.store(0, Ordering::Release);
    TRACE_EVENTS.store(0, Ordering::Release);
    PERMISSION_MASK.store(0, Ordering::Release);
    DENIED_SYSCALLS.store(0, Ordering::Release);
    PERMISSION_AUDIT_EVENTS.store(0, Ordering::Release);
    YIELD_KERNEL_RETURNS.store(0, Ordering::Release);
    NEURAL_MODEL_ASSERTS.store(0, Ordering::Release);
    NEURAL_PRIMITIVE_CALLS.store(0, Ordering::Release);
    NEURAL_TOKENS_EMITTED.store(0, Ordering::Release);
    NEURAL_LAST_TOKEN.store(0, Ordering::Release);
    NEURAL_RECEIPT_ACCUMULATOR.store(0, Ordering::Release);
    MAILBOX_LEN.store(0, Ordering::Release);
}

fn summary(separate_cr3: bool) -> ProcessSummary {
    ProcessSummary {
        exit_status: EXIT_STATUS.load(Ordering::Acquire),
        syscall_count: SYSCALL_COUNT.load(Ordering::Acquire),
        console_bytes: CONSOLE_BYTES.load(Ordering::Acquire),
        unknown_rejected: UNKNOWN_REJECTED.load(Ordering::Acquire),
        separate_cr3,
        ipc_roundtrip: IPC_SENDS.load(Ordering::Acquire) == 1
            && IPC_RECVS.load(Ordering::Acquire) == 1,
        trace_events: TRACE_EVENTS.load(Ordering::Acquire),
        permission_mask: PERMISSION_MASK.load(Ordering::Acquire),
        denied_syscalls: DENIED_SYSCALLS.load(Ordering::Acquire),
        permission_audit_events: PERMISSION_AUDIT_EVENTS.load(Ordering::Acquire),
        yield_kernel_returns: YIELD_KERNEL_RETURNS.load(Ordering::Acquire),
        neural_model_asserts: NEURAL_MODEL_ASSERTS.load(Ordering::Acquire),
        neural_primitive_calls: NEURAL_PRIMITIVE_CALLS.load(Ordering::Acquire),
        neural_tokens_emitted: NEURAL_TOKENS_EMITTED.load(Ordering::Acquire),
        neural_last_token: NEURAL_LAST_TOKEN.load(Ordering::Acquire),
        neural_receipt_accumulator: NEURAL_RECEIPT_ACCUMULATOR.load(Ordering::Acquire),
        trap: trap_action(),
    }
}

fn valid_user_read(pointer: u64, length: usize) -> bool {
    if length > MAX_CONSOLE_WRITE {
        return false;
    }
    let Some(end) = pointer.checked_add(length as u64) else {
        return false;
    };
    pointer >= USER_CODE_START && end <= USER_CODE_START + 4096
}

fn valid_user_write(pointer: u64, length: usize) -> bool {
    if length > 64 {
        return false;
    }
    let Some(end) = pointer.checked_add(length as u64) else {
        return false;
    };
    pointer >= USER_STACK_BOTTOM && end <= USER_STACK_TOP
}

#[unsafe(no_mangle)]
extern "C" fn casulo_syscall_dispatch(number: u64, arg0: u64, arg1: u64) -> i64 {
    SYSCALL_COUNT.fetch_add(1, Ordering::AcqRel);
    if number > 9 {
        UNKNOWN_REJECTED.store(true, Ordering::Release);
        return ENOSYS;
    }
    if PERMISSION_MASK.load(Ordering::Acquire) & (1u64 << number) == 0 {
        DENIED_SYSCALLS.fetch_add(1, Ordering::AcqRel);
        PERMISSION_AUDIT_EVENTS.fetch_add(1, Ordering::AcqRel);
        return EPERM;
    }
    match number {
        0 => {
            let status = (arg0 & 0xff) as i64;
            EXIT_STATUS.store(status, Ordering::Release);
            EXIT_REQUESTED.store(true, Ordering::Release);
            CASULO_TRAP_ACTION.store(UserTrap::Exit as u8, Ordering::Release);
            status
        }
        1 => {
            let length = arg1 as usize;
            if !valid_user_read(arg0, length) {
                return EFAULT;
            }
            let bytes = unsafe { core::slice::from_raw_parts(arg0 as *const u8, length) };
            let mut serial = Serial::init();
            for &byte in bytes {
                serial.write_byte(byte);
            }
            CONSOLE_BYTES.fetch_add(length as u64, Ordering::AcqRel);
            length as i64
        }
        2 => interrupts::timer_ticks() as i64,
        3 => {
            CASULO_TRAP_ACTION.store(UserTrap::Yield as u8, Ordering::Release);
            0
        }
        4 => {
            let length = arg1 as usize;
            if length > 64 || !valid_user_read(arg0, length) {
                return EFAULT;
            }
            unsafe {
                core::ptr::copy_nonoverlapping(
                    arg0 as *const u8,
                    core::ptr::addr_of_mut!(MAILBOX).cast::<u8>(),
                    length,
                );
            }
            MAILBOX_LEN.store(length as u64, Ordering::Release);
            IPC_SENDS.fetch_add(1, Ordering::AcqRel);
            length as i64
        }
        5 => {
            let capacity = arg1 as usize;
            let length = MAILBOX_LEN.load(Ordering::Acquire) as usize;
            if length == 0 || capacity < length || !valid_user_write(arg0, length) {
                return EFAULT;
            }
            unsafe {
                core::ptr::copy_nonoverlapping(
                    core::ptr::addr_of!(MAILBOX).cast::<u8>(),
                    arg0 as *mut u8,
                    length,
                );
            }
            MAILBOX_LEN.store(0, Ordering::Release);
            IPC_RECVS.fetch_add(1, Ordering::AcqRel);
            length as i64
        }
        6 => {
            let length = arg1 as usize;
            if !valid_user_read(arg0, length) {
                return EFAULT;
            }
            TRACE_EVENTS.fetch_add(1, Ordering::AcqRel);
            length as i64
        }
        7 => neural_model_assert(arg0, arg1 as usize),
        8 => neural_dot_i16x4(arg0, arg1 as usize),
        9 => neural_token_emit(arg0, arg1),
        _ => unreachable!(),
    }
}

fn neural_model_assert(pointer: u64, length: usize) -> i64 {
    if length != 64 || !valid_user_read(pointer, length) {
        return EFAULT;
    }
    let bytes = unsafe { core::slice::from_raw_parts(pointer as *const u8, length) };
    if &bytes[..8] != b"CSNABI01"
        || u32::from_le_bytes(bytes[8..12].try_into().unwrap()) != 1
        || !bytes[16..48].iter().any(|byte| *byte != 0)
    {
        return EINVAL;
    }
    let context = u32::from_le_bytes(bytes[48..52].try_into().unwrap());
    let precision = u32::from_le_bytes(bytes[52..56].try_into().unwrap());
    if context == 0 || context > 32_768 || precision != 1 {
        return EINVAL;
    }
    NEURAL_MODEL_ASSERTS.fetch_add(1, Ordering::AcqRel);
    0
}

fn neural_dot_i16x4(pointer: u64, length: usize) -> i64 {
    if length != 24 || !valid_user_write(pointer, length) {
        return EFAULT;
    }
    let bytes = unsafe { core::slice::from_raw_parts_mut(pointer as *mut u8, length) };
    let mut dot = 0i32;
    for index in 0..4 {
        let offset = index * 2;
        let lhs = i16::from_le_bytes(bytes[offset..offset + 2].try_into().unwrap());
        let rhs_offset = 8 + offset;
        let rhs = i16::from_le_bytes(bytes[rhs_offset..rhs_offset + 2].try_into().unwrap());
        dot = dot.saturating_add(i32::from(lhs).saturating_mul(i32::from(rhs)));
    }
    bytes[16..20].copy_from_slice(&dot.to_le_bytes());
    let receipt = 0x4e41_4249u32 ^ dot as u32;
    bytes[20..24].copy_from_slice(&receipt.to_le_bytes());
    NEURAL_PRIMITIVE_CALLS.fetch_add(1, Ordering::AcqRel);
    NEURAL_RECEIPT_ACCUMULATOR.fetch_xor(u64::from(receipt), Ordering::AcqRel);
    i64::from(dot)
}

fn neural_token_emit(token: u64, evidence: u64) -> i64 {
    if token > u32::MAX as u64 || evidence == 0 {
        return EINVAL;
    }
    NEURAL_LAST_TOKEN.store(token, Ordering::Release);
    NEURAL_TOKENS_EMITTED.fetch_add(1, Ordering::AcqRel);
    NEURAL_RECEIPT_ACCUMULATOR.fetch_xor(evidence.rotate_left(17), Ordering::AcqRel);
    token as i64
}
