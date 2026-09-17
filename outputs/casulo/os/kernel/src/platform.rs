//! Bounded QEMU platform exits used by explicit probe images.

use x86_64::instructions::{hlt, interrupts, port::Port};

/// Request an x86 reset through the 8042 controller. The QEMU probe runner
/// uses `-no-reboot`, so a recognized reset exits QEMU instead of looping.
pub fn request_reboot() -> ! {
    interrupts::disable();
    unsafe {
        let mut status: Port<u8> = Port::new(0x64);
        for _ in 0..100_000 {
            if status.read() & 0x02 == 0 {
                status.write(0xfe);
                break;
            }
            core::hint::spin_loop();
        }
    }
    loop {
        hlt();
    }
}
