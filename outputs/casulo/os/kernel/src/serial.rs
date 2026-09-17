use core::fmt;
use x86_64::instructions::port::Port;

pub struct Serial;

impl Serial {
    pub fn init() -> Self {
        unsafe {
            let mut interrupt_enable: Port<u8> = Port::new(0x3f9);
            let mut line_control: Port<u8> = Port::new(0x3fb);
            let mut divisor_low: Port<u8> = Port::new(0x3f8);
            let mut divisor_high: Port<u8> = Port::new(0x3f9);
            let mut fifo_control: Port<u8> = Port::new(0x3fa);
            let mut modem_control: Port<u8> = Port::new(0x3fc);
            interrupt_enable.write(0x00);
            line_control.write(0x80);
            divisor_low.write(0x03);
            divisor_high.write(0x00);
            line_control.write(0x03);
            fifo_control.write(0xc7);
            // DTR/RTS + OUT2; loopback must remain disabled so host chardev
            // input reaches the UART receive FIFO.
            modem_control.write(0x0b);
            // Reading these status registers clears any stale boot firmware
            // condition without consuming host payload from the data port.
            let mut line_status: Port<u8> = Port::new(0x3fd);
            let mut modem_status: Port<u8> = Port::new(0x3fe);
            let _ = line_status.read();
            let _ = modem_status.read();
        }
        Self
    }

    pub(crate) fn write_byte(&mut self, byte: u8) {
        unsafe {
            let mut data: Port<u8> = Port::new(0x3f8);
            data.write(byte);
        }
    }

    /// Reads one byte only when the UART has received data.
    ///
    /// The generative VM profile uses this bounded, polling-only surface as a
    /// capability-scoped bridge. It deliberately exposes no DMA, filesystem,
    /// network, host pointer, or arbitrary device access to the guest.
    pub(crate) fn try_read_byte(&mut self) -> Option<u8> {
        unsafe {
            let mut line_status: Port<u8> = Port::new(0x3fd);
            let status = line_status.read();
            if status & 0x01 == 0 {
                return None;
            }
            let mut data: Port<u8> = Port::new(0x3f8);
            Some(data.read())
        }
    }

    pub(crate) fn line_status(&mut self) -> u8 {
        unsafe {
            let mut line_status: Port<u8> = Port::new(0x3fd);
            line_status.read()
        }
    }
}

impl fmt::Write for Serial {
    fn write_str(&mut self, text: &str) -> fmt::Result {
        for byte in text.bytes() {
            if byte == b'\n' {
                self.write_byte(b'\r');
            }
            self.write_byte(byte);
        }
        Ok(())
    }
}
