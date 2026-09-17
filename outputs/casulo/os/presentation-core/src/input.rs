//! Bounded Scan Code Set 1 decoder used by the first Native text surface.
//!
//! Device I/O stays in the kernel adapter.  This module only transforms an
//! already-read byte into a fixed-capacity line and can therefore be tested on
//! the host without granting presentation code access to hardware.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum InputUpdate {
    Ignored,
    Changed,
    Submitted,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum InputError {
    CapacityExceeded,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct KeyboardLine<const N: usize> {
    bytes: [u8; N],
    len: usize,
    left_shift: bool,
    right_shift: bool,
}

impl<const N: usize> KeyboardLine<N> {
    pub const fn new() -> Self {
        Self {
            bytes: [0; N],
            len: 0,
            left_shift: false,
            right_shift: false,
        }
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes[..self.len]
    }

    pub const fn len(&self) -> usize {
        self.len
    }

    pub const fn is_empty(&self) -> bool {
        self.len == 0
    }

    pub fn clear(&mut self) {
        self.bytes[..self.len].fill(0);
        self.len = 0;
    }

    pub fn feed_set1(&mut self, scan_code: u8) -> Result<InputUpdate, InputError> {
        match scan_code {
            0x2a => {
                self.left_shift = true;
                return Ok(InputUpdate::Ignored);
            }
            0xaa => {
                self.left_shift = false;
                return Ok(InputUpdate::Ignored);
            }
            0x36 => {
                self.right_shift = true;
                return Ok(InputUpdate::Ignored);
            }
            0xb6 => {
                self.right_shift = false;
                return Ok(InputUpdate::Ignored);
            }
            0x0e => {
                if self.len > 0 {
                    self.len -= 1;
                    self.bytes[self.len] = 0;
                    return Ok(InputUpdate::Changed);
                }
                return Ok(InputUpdate::Ignored);
            }
            0x1c => return Ok(InputUpdate::Submitted),
            code if code & 0x80 != 0 => return Ok(InputUpdate::Ignored),
            _ => {}
        }
        let Some(mut byte) = set1_ascii(scan_code) else {
            return Ok(InputUpdate::Ignored);
        };
        if self.left_shift || self.right_shift {
            byte = shifted(byte);
        }
        if self.len == N {
            return Err(InputError::CapacityExceeded);
        }
        self.bytes[self.len] = byte;
        self.len += 1;
        Ok(InputUpdate::Changed)
    }
}

impl<const N: usize> Default for KeyboardLine<N> {
    fn default() -> Self {
        Self::new()
    }
}

pub fn self_test() -> bool {
    let mut line = KeyboardLine::<16>::new();
    let casulo = [0x2e, 0x1e, 0x1f, 0x16, 0x26, 0x18];
    let accepted = casulo
        .into_iter()
        .all(|code| line.feed_set1(code) == Ok(InputUpdate::Changed));
    accepted
        && line.as_bytes() == b"casulo"
        && line.feed_set1(0x1c) == Ok(InputUpdate::Submitted)
        && line.as_bytes() == b"casulo"
}

const fn shifted(byte: u8) -> u8 {
    match byte {
        b'a'..=b'z' => byte - 32,
        b'1' => b'!',
        b'2' => b'@',
        b'3' => b'#',
        b'4' => b'$',
        b'5' => b'%',
        b'6' => b'^',
        b'7' => b'&',
        b'8' => b'*',
        b'9' => b'(',
        b'0' => b')',
        b'-' => b'_',
        b'=' => b'+',
        b',' => b'<',
        b'.' => b'>',
        b'/' => b'?',
        b';' => b':',
        b'\'' => b'"',
        _ => byte,
    }
}

const fn set1_ascii(code: u8) -> Option<u8> {
    match code {
        0x02 => Some(b'1'),
        0x03 => Some(b'2'),
        0x04 => Some(b'3'),
        0x05 => Some(b'4'),
        0x06 => Some(b'5'),
        0x07 => Some(b'6'),
        0x08 => Some(b'7'),
        0x09 => Some(b'8'),
        0x0a => Some(b'9'),
        0x0b => Some(b'0'),
        0x0c => Some(b'-'),
        0x0d => Some(b'='),
        0x10 => Some(b'q'),
        0x11 => Some(b'w'),
        0x12 => Some(b'e'),
        0x13 => Some(b'r'),
        0x14 => Some(b't'),
        0x15 => Some(b'y'),
        0x16 => Some(b'u'),
        0x17 => Some(b'i'),
        0x18 => Some(b'o'),
        0x19 => Some(b'p'),
        0x1e => Some(b'a'),
        0x1f => Some(b's'),
        0x20 => Some(b'd'),
        0x21 => Some(b'f'),
        0x22 => Some(b'g'),
        0x23 => Some(b'h'),
        0x24 => Some(b'j'),
        0x25 => Some(b'k'),
        0x26 => Some(b'l'),
        0x27 => Some(b';'),
        0x28 => Some(b'\''),
        0x2c => Some(b'z'),
        0x2d => Some(b'x'),
        0x2e => Some(b'c'),
        0x2f => Some(b'v'),
        0x30 => Some(b'b'),
        0x31 => Some(b'n'),
        0x32 => Some(b'm'),
        0x33 => Some(b','),
        0x34 => Some(b'.'),
        0x35 => Some(b'/'),
        0x39 => Some(b' '),
        _ => None,
    }
}
