use crate::{SceneForm, SceneState};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PixelOrder {
    Rgb,
    Bgr,
    Gray,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Color {
    pub red: u8,
    pub green: u8,
    pub blue: u8,
}

impl Color {
    const fn new(red: u8, green: u8, blue: u8) -> Self {
        Self { red, green, blue }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RenderError {
    InvalidGeometry,
    UnsupportedPixelLayout,
    BufferTooSmall,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RenderReceipt {
    pub framebuffer_fingerprint: u64,
    pub pixels_written: u64,
    pub form: SceneForm,
    pub receipt_nodes: u16,
}

pub struct Surface<'a> {
    buffer: &'a mut [u8],
    width: usize,
    height: usize,
    stride: usize,
    bytes_per_pixel: usize,
    order: PixelOrder,
    pixels_written: u64,
}

impl<'a> Surface<'a> {
    pub fn new(
        buffer: &'a mut [u8],
        width: usize,
        height: usize,
        stride: usize,
        bytes_per_pixel: usize,
        order: PixelOrder,
    ) -> Result<Self, RenderError> {
        if width == 0 || height == 0 || stride < width || bytes_per_pixel == 0 {
            return Err(RenderError::InvalidGeometry);
        }
        let minimum = stride
            .checked_mul(height)
            .and_then(|pixels| pixels.checked_mul(bytes_per_pixel))
            .ok_or(RenderError::InvalidGeometry)?;
        if buffer.len() < minimum {
            return Err(RenderError::BufferTooSmall);
        }
        match order {
            PixelOrder::Rgb | PixelOrder::Bgr if bytes_per_pixel < 3 => {
                return Err(RenderError::UnsupportedPixelLayout);
            }
            PixelOrder::Gray if bytes_per_pixel < 1 => {
                return Err(RenderError::UnsupportedPixelLayout);
            }
            _ => {}
        }
        Ok(Self {
            buffer,
            width,
            height,
            stride,
            bytes_per_pixel,
            order,
            pixels_written: 0,
        })
    }

    pub const fn dimensions(&self) -> (usize, usize) {
        (self.width, self.height)
    }

    pub fn clear(&mut self, color: Color) {
        for y in 0..self.height {
            for x in 0..self.width {
                self.pixel(x as isize, y as isize, color);
            }
        }
    }

    pub fn fill_rect(&mut self, x: isize, y: isize, width: usize, height: usize, color: Color) {
        for row in 0..height {
            for column in 0..width {
                self.pixel(x + column as isize, y + row as isize, color);
            }
        }
    }

    pub fn line(&mut self, mut x0: isize, mut y0: isize, x1: isize, y1: isize, color: Color) {
        let dx = (x1 - x0).abs();
        let sx = if x0 < x1 { 1 } else { -1 };
        let dy = -(y1 - y0).abs();
        let sy = if y0 < y1 { 1 } else { -1 };
        let mut error = dx + dy;
        loop {
            self.pixel(x0, y0, color);
            if x0 == x1 && y0 == y1 {
                break;
            }
            let doubled = 2 * error;
            if doubled >= dy {
                error += dy;
                x0 += sx;
            }
            if doubled <= dx {
                error += dx;
                y0 += sy;
            }
        }
    }

    pub fn fill_circle(&mut self, center_x: isize, center_y: isize, radius: usize, color: Color) {
        let radius = radius as isize;
        let squared = radius * radius;
        for y in -radius..=radius {
            for x in -radius..=radius {
                if x * x + y * y <= squared {
                    self.pixel(center_x + x, center_y + y, color);
                }
            }
        }
    }

    pub fn text(&mut self, x: isize, y: isize, value: &[u8], scale: usize, color: Color) {
        let mut cursor_x = x;
        let advance = (6 * scale) as isize;
        for byte in value {
            let character = if byte.is_ascii_lowercase() {
                byte.to_ascii_uppercase()
            } else if byte.is_ascii() {
                *byte
            } else {
                b'?'
            };
            self.glyph(cursor_x, y, character, scale, color);
            cursor_x += advance;
            if cursor_x >= self.width as isize - advance {
                break;
            }
        }
    }

    fn glyph(&mut self, x: isize, y: isize, character: u8, scale: usize, color: Color) {
        let rows = glyph(character);
        for (row, bits) in rows.iter().enumerate() {
            for column in 0..5 {
                if bits & (1 << (4 - column)) != 0 {
                    self.fill_rect(
                        x + (column * scale) as isize,
                        y + (row * scale) as isize,
                        scale,
                        scale,
                        color,
                    );
                }
            }
        }
    }

    fn pixel(&mut self, x: isize, y: isize, color: Color) {
        if x < 0 || y < 0 || x >= self.width as isize || y >= self.height as isize {
            return;
        }
        let offset = (y as usize * self.stride + x as usize) * self.bytes_per_pixel;
        match self.order {
            PixelOrder::Rgb => {
                self.buffer[offset] = color.red;
                self.buffer[offset + 1] = color.green;
                self.buffer[offset + 2] = color.blue;
            }
            PixelOrder::Bgr => {
                self.buffer[offset] = color.blue;
                self.buffer[offset + 1] = color.green;
                self.buffer[offset + 2] = color.red;
            }
            PixelOrder::Gray => {
                self.buffer[offset] = ((u16::from(color.red) * 54
                    + u16::from(color.green) * 183
                    + u16::from(color.blue) * 19)
                    / 256) as u8;
            }
        }
        for byte in 3..self.bytes_per_pixel {
            self.buffer[offset + byte] = 0;
        }
        self.pixels_written = self.pixels_written.saturating_add(1);
    }

    fn fingerprint(&self) -> u64 {
        // Stable, non-cryptographic render fingerprint for deterministic CI.
        // Artifact integrity continues to use SHA-256 outside the framebuffer.
        let mut hash = 0xcbf29ce484222325_u64;
        for byte in self.buffer.iter() {
            hash ^= u64::from(*byte);
            hash = hash.wrapping_mul(0x100000001b3);
        }
        hash
    }
}

const INK: Color = Color::new(7, 11, 18);
const DEEP_BLUE: Color = Color::new(18, 40, 61);
const BLUE: Color = Color::new(42, 111, 151);
const AMBER: Color = Color::new(226, 166, 74);
const IVORY: Color = Color::new(235, 232, 219);
const MUTED: Color = Color::new(135, 151, 163);
const ERROR: Color = Color::new(190, 76, 72);

pub fn render_scene(surface: &mut Surface<'_>, scene: &SceneState) -> RenderReceipt {
    let (width, height) = surface.dimensions();
    surface.clear(INK);
    surface.fill_rect(0, 0, width, 2, AMBER);
    surface.text(24, 20, b"CASULO", 2, IVORY);
    surface.text(24, 42, form_label(scene.form), 1, MUTED);

    let center_x = (width / 2) as isize;
    let center_y = (height * 43 / 100) as isize;
    let radius = core::cmp::max(22, core::cmp::min(width, height) / 10);
    surface.fill_circle(center_x, center_y, radius + 8, DEEP_BLUE);
    surface.fill_circle(center_x, center_y, radius, form_color(scene.form));
    surface.fill_circle(center_x, center_y, core::cmp::max(5, radius / 3), AMBER);

    const NODES: [(isize, isize); 16] = [
        (-130, -50),
        (-100, -100),
        (-42, -125),
        (42, -125),
        (100, -100),
        (130, -50),
        (140, 20),
        (112, 82),
        (55, 120),
        (-20, 132),
        (-86, 105),
        (-132, 58),
        (-155, 0),
        (-82, -40),
        (78, -42),
        (0, 92),
    ];
    let visible = core::cmp::min(usize::from(scene.receipt_count), NODES.len());
    for (index, (offset_x, offset_y)) in NODES[..visible].iter().enumerate() {
        let node_x = center_x + *offset_x;
        let node_y = center_y + *offset_y;
        surface.line(center_x, center_y, node_x, node_y, DEEP_BLUE);
        surface.fill_circle(node_x, node_y, 4 + index % 2, AMBER);
    }

    let text_y = height.saturating_sub(82) as isize;
    if scene.message.present && !scene.message.text.is_empty() {
        surface.text(24, text_y - 22, scene.message.text.as_bytes(), 1, IVORY);
    }
    surface.text(24, text_y, scene.notice.as_bytes(), 1, MUTED);
    if !scene.recoverable_error.is_empty() {
        surface.fill_rect(20, text_y + 16, width.saturating_sub(40), 2, ERROR);
    }

    RenderReceipt {
        framebuffer_fingerprint: surface.fingerprint(),
        pixels_written: surface.pixels_written,
        form: scene.form,
        receipt_nodes: visible as u16,
    }
}

const fn form_color(form: SceneForm) -> Color {
    match form {
        SceneForm::Materialized => Color::new(42, 128, 117),
        SceneForm::RecoverableFailure => ERROR,
        SceneForm::Cancelled => Color::new(91, 100, 110),
        SceneForm::Formation | SceneForm::FirstForm => BLUE,
        _ => DEEP_BLUE,
    }
}

const fn form_label(form: SceneForm) -> &'static [u8] {
    match form {
        SceneForm::Silence => b"SILENCE",
        SceneForm::Presence => b"PRESENCE",
        SceneForm::Listening => b"LISTENING",
        SceneForm::Thinking => b"THINKING",
        SceneForm::Conversation => b"CONVERSATION",
        SceneForm::FirstForm => b"FIRST FORM",
        SceneForm::Formation => b"FORMATION",
        SceneForm::Materialized => b"MATERIALIZED",
        SceneForm::Cancelled => b"CANCELLED",
        SceneForm::RecoverableFailure => b"RECOVERABLE FAILURE",
    }
}

const fn glyph(character: u8) -> [u8; 7] {
    match character {
        b'A' => [0x0e, 0x11, 0x11, 0x1f, 0x11, 0x11, 0x11],
        b'B' => [0x1e, 0x11, 0x11, 0x1e, 0x11, 0x11, 0x1e],
        b'C' => [0x0e, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0e],
        b'D' => [0x1e, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1e],
        b'E' => [0x1f, 0x10, 0x10, 0x1e, 0x10, 0x10, 0x1f],
        b'F' => [0x1f, 0x10, 0x10, 0x1e, 0x10, 0x10, 0x10],
        b'G' => [0x0e, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0f],
        b'H' => [0x11, 0x11, 0x11, 0x1f, 0x11, 0x11, 0x11],
        b'I' => [0x0e, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0e],
        b'J' => [0x07, 0x02, 0x02, 0x02, 0x12, 0x12, 0x0c],
        b'K' => [0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11],
        b'L' => [0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1f],
        b'M' => [0x11, 0x1b, 0x15, 0x15, 0x11, 0x11, 0x11],
        b'N' => [0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11],
        b'O' => [0x0e, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0e],
        b'P' => [0x1e, 0x11, 0x11, 0x1e, 0x10, 0x10, 0x10],
        b'Q' => [0x0e, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0d],
        b'R' => [0x1e, 0x11, 0x11, 0x1e, 0x14, 0x12, 0x11],
        b'S' => [0x0f, 0x10, 0x10, 0x0e, 0x01, 0x01, 0x1e],
        b'T' => [0x1f, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04],
        b'U' => [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0e],
        b'V' => [0x11, 0x11, 0x11, 0x11, 0x11, 0x0a, 0x04],
        b'W' => [0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0a],
        b'X' => [0x11, 0x11, 0x0a, 0x04, 0x0a, 0x11, 0x11],
        b'Y' => [0x11, 0x11, 0x0a, 0x04, 0x04, 0x04, 0x04],
        b'Z' => [0x1f, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1f],
        b'0' => [0x0e, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0e],
        b'1' => [0x04, 0x0c, 0x04, 0x04, 0x04, 0x04, 0x0e],
        b'2' => [0x0e, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1f],
        b'3' => [0x1e, 0x01, 0x01, 0x0e, 0x01, 0x01, 0x1e],
        b'4' => [0x02, 0x06, 0x0a, 0x12, 0x1f, 0x02, 0x02],
        b'5' => [0x1f, 0x10, 0x10, 0x1e, 0x01, 0x01, 0x1e],
        b'6' => [0x0e, 0x10, 0x10, 0x1e, 0x11, 0x11, 0x0e],
        b'7' => [0x1f, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
        b'8' => [0x0e, 0x11, 0x11, 0x0e, 0x11, 0x11, 0x0e],
        b'9' => [0x0e, 0x11, 0x11, 0x0f, 0x01, 0x01, 0x0e],
        b'-' => [0, 0, 0, 0x1f, 0, 0, 0],
        b'.' => [0, 0, 0, 0, 0, 0x0c, 0x0c],
        b':' => [0, 0x0c, 0x0c, 0, 0x0c, 0x0c, 0],
        b' ' => [0; 7],
        _ => [0x0e, 0x11, 0x01, 0x02, 0x04, 0, 0x04],
    }
}
