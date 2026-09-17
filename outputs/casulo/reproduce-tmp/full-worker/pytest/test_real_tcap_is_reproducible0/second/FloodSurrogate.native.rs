#![no_std]
#![no_main]

const INPUTS: usize = 8;
const HIDDEN: usize = 8;
const PARAMS: usize = INPUTS * HIDDEN + HIDDEN + HIDDEN + 1;
const EPOCHS: usize = 400;
const LEARNING_RATE: f64 = 0.018;
const MAX_RECORDS: usize = 4096;

#[repr(C)]
pub struct LearnContext {
    pub inputs: *const f64,
    pub targets: *const f64,
    pub parameters: *mut f64,
    pub gradients: *mut f64,
    pub records: usize,
    pub epochs: usize,
    pub learning_rate: f64,
    pub initial_loss: *mut f64,
    pub final_loss: *mut f64,

}

#[inline(always)]
fn relu(value: f64) -> f64 { if value > 0.0 { value } else { 0.0 } }

unsafe fn predict(row: *const f64, parameters: *const f64) -> f64 {
    let mut hidden = [0.0f64; HIDDEN];
    let b1 = INPUTS * HIDDEN;
    let w2 = b1 + HIDDEN;
    let b2 = w2 + HIDDEN;
    let mut j = 0;
    while j < HIDDEN { hidden[j] = *parameters.add(b1 + j); j += 1; }
    let mut k = 0;
    while k < INPUTS {
        let input = *row.add(k);
        j = 0;
        while j < HIDDEN {
            hidden[j] += input * *parameters.add(k * HIDDEN + j);
            j += 1;
        }
        k += 1;
    }
    let mut output = *parameters.add(b2);
    j = 0;
    while j < HIDDEN { output += relu(hidden[j]) * *parameters.add(w2 + j); j += 1; }
    output
}

unsafe fn evaluate(ctx: &LearnContext) -> f64 {
    let mut total = 0.0;
    let mut i = 0;
    while i < ctx.records {
        let error = predict(ctx.inputs.add(i * INPUTS), ctx.parameters) - *ctx.targets.add(i);
        total += error * error;
        i += 1;
    }
    total / ctx.records as f64
}

#[unsafe(no_mangle)]
#[unsafe(link_section = ".text.entry")]
pub unsafe extern "sysv64" fn casulo_learn_entry(context: *mut LearnContext) -> i32 {
    if context.is_null() { return -1; }
    let ctx = &mut *context;
    if ctx.inputs.is_null() || ctx.targets.is_null() || ctx.parameters.is_null()
        || ctx.gradients.is_null() || ctx.initial_loss.is_null() || ctx.final_loss.is_null()
         { return -2; }
    if ctx.records == 0 || ctx.records > MAX_RECORDS { return -3; }
    if ctx.epochs != EPOCHS || ctx.learning_rate.to_bits() != LEARNING_RATE.to_bits() { return -4; }

    *ctx.initial_loss = evaluate(ctx);
    let mut epoch = 0;
    while epoch < EPOCHS {
        let mut q = 0;
        while q < PARAMS { *ctx.gradients.add(q) = 0.0; q += 1; }
        let mut i = 0;
        while i < ctx.records {
            let row = ctx.inputs.add(i * INPUTS);
            let mut pre = [0.0f64; HIDDEN];
            let mut hidden = [0.0f64; HIDDEN];
            let mut delta = [0.0f64; HIDDEN];
            let b1 = INPUTS * HIDDEN;
            let w2 = b1 + HIDDEN;
            let b2 = w2 + HIDDEN;
            let mut j = 0;
            while j < HIDDEN { pre[j] = *ctx.parameters.add(b1 + j); j += 1; }
            let mut k = 0;
            while k < INPUTS {
                let input = *row.add(k);
                j = 0;
                while j < HIDDEN { pre[j] += input * *ctx.parameters.add(k * HIDDEN + j); j += 1; }
                k += 1;
            }
            let mut prediction = *ctx.parameters.add(b2);
            j = 0;
            while j < HIDDEN {
                hidden[j] = relu(pre[j]);
                prediction += hidden[j] * *ctx.parameters.add(w2 + j);
                j += 1;
            }
            let output_gradient = (2.0 / ctx.records as f64) * (prediction - *ctx.targets.add(i));
            *ctx.gradients.add(b2) += output_gradient;
            j = 0;
            while j < HIDDEN {
                let derivative = if pre[j] > 0.0 { 1.0 } else { 0.0 };
                delta[j] = output_gradient * *ctx.parameters.add(w2 + j) * derivative;
                *ctx.gradients.add(w2 + j) += output_gradient * hidden[j];
                *ctx.gradients.add(b1 + j) += delta[j];
                j += 1;
            }
            k = 0;
            while k < INPUTS {
                let input = *row.add(k);
                j = 0;
                while j < HIDDEN {
                    *ctx.gradients.add(k * HIDDEN + j) += delta[j] * input;
                    j += 1;
                }
                k += 1;
            }
            i += 1;
        }

        q = 0;
        while q < PARAMS {
            *ctx.parameters.add(q) -= LEARNING_RATE * *ctx.gradients.add(q);
            q += 1;
        }

        epoch += 1;
    }
    *ctx.final_loss = evaluate(ctx);
    0
}

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { loop { core::hint::spin_loop(); } }
