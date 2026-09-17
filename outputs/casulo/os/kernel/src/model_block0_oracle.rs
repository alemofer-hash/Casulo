//! Frozen independent NumPy oracle for NP6 Qwen3 block zero.
//!
//! Values originate from `block0-oracle-attempt-3.json`. Native scalar and
//! NumPy vectorized matvecs use different accumulation orders, so this gate
//! compares count, sum, squared L2, minimum, and maximum under predeclared
//! tolerances. It does not pretend cross-runtime bit identity.

use casulo_native_model::{QwenBlock0Receipt, StageSummary};

#[derive(Clone, Copy)]
struct ExpectedStage {
    values: u32,
    sum: f64,
    square_sum: f64,
    minimum: f32,
    maximum: f32,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct OracleReceipt {
    pub stages_compared: u32,
    pub mismatch_mask: u64,
}

impl OracleReceipt {
    pub const fn passed_for(self, tokens: u32) -> bool {
        self.stages_compared == tokens * 19 && self.mismatch_mask == 0
    }
}

pub fn verify(receipt: &QwenBlock0Receipt) -> OracleReceipt {
    let mut result = OracleReceipt::default();
    for token_index in 0..receipt.tokens_completed as usize {
        let token = &receipt.token[token_index];
        let observed = [
            &token.embedding,
            &token.attn_norm,
            &token.query_projection,
            &token.key_projection,
            &token.value_projection,
            &token.query_norm,
            &token.key_norm,
            &token.query_rope,
            &token.key_rope,
            &token.attention_weights,
            &token.attention_context,
            &token.attention_projection,
            &token.attention_residual,
            &token.ffn_norm,
            &token.ffn_gate,
            &token.ffn_up,
            &token.ffn_activated,
            &token.ffn_down,
            &token.block_output,
        ];
        for (stage_index, stage) in observed.into_iter().enumerate() {
            let absolute_index = token_index * 19 + stage_index;
            result.stages_compared += 1;
            if !stage_matches(stage, &EXPECTED[token_index][stage_index]) {
                result.mismatch_mask |= 1u64 << absolute_index;
            }
        }
    }
    result
}

fn stage_matches(observed: &StageSummary, expected: &ExpectedStage) -> bool {
    observed.values == expected.values
        && within_f64(observed.sum_f64, expected.sum, 0.001, 0.0005)
        && within_f64(observed.square_sum_f64, expected.square_sum, 0.001, 0.0005)
        && within_f32(observed.minimum, expected.minimum, 0.0001, 0.0005)
        && within_f32(observed.maximum, expected.maximum, 0.0001, 0.0005)
}

fn within_f64(observed: f64, expected: f64, absolute: f64, relative: f64) -> bool {
    (observed - expected).abs() <= absolute.max(expected.abs() * relative)
}

fn within_f32(observed: f32, expected: f32, absolute: f32, relative: f32) -> bool {
    (observed - expected).abs() <= absolute.max(expected.abs() * relative)
}

const EXPECTED: [[ExpectedStage; 19]; 2] = [
    [
        ExpectedStage {
            values: 2560,
            sum: 0.99399781227111816,
            square_sum: 1.4237433992706698,
            minimum: -0.0704898834,
            maximum: 0.0886917114,
        },
        ExpectedStage {
            values: 2560,
            sum: 1.3048116295831278,
            square_sum: 2.5576938934182492,
            minimum: -0.224236161,
            maximum: 0.222158656,
        },
        ExpectedStage {
            values: 4096,
            sum: 1.2685805385699496,
            square_sum: 13.894230238187051,
            minimum: -0.459118903,
            maximum: 0.769218922,
        },
        ExpectedStage {
            values: 1024,
            sum: -0.38122440362349153,
            square_sum: 3.4125093909439004,
            minimum: -0.318799287,
            maximum: 0.251607686,
        },
        ExpectedStage {
            values: 1024,
            sum: 1.0910895231645554,
            square_sum: 1.1247445789966033,
            minimum: -0.237743974,
            maximum: 0.287152469,
        },
        ExpectedStage {
            values: 4096,
            sum: -55.051624851310407,
            square_sum: 11104.945670864294,
            minimum: -10.5248432,
            maximum: 11.4424152,
        },
        ExpectedStage {
            values: 1024,
            sum: 125.24756313388934,
            square_sum: 267986.42787352903,
            minimum: -254.9216,
            maximum: 247.063644,
        },
        ExpectedStage {
            values: 4096,
            sum: -55.051624851310407,
            square_sum: 11104.945670864294,
            minimum: -10.5248432,
            maximum: 11.4424152,
        },
        ExpectedStage {
            values: 1024,
            sum: 125.24756313388934,
            square_sum: 267986.42787352903,
            minimum: -254.9216,
            maximum: 247.063644,
        },
        ExpectedStage {
            values: 32,
            sum: 32.0,
            square_sum: 32.000000000000007,
            minimum: 1.0,
            maximum: 1.0,
        },
        ExpectedStage {
            values: 4096,
            sum: 4.3643580926582217,
            square_sum: 4.4989783159864132,
            minimum: -0.237743974,
            maximum: 0.287152469,
        },
        ExpectedStage {
            values: 2560,
            sum: -2.5293783189263195,
            square_sum: 8.3419168853679313,
            minimum: -0.340329766,
            maximum: 0.702009201,
        },
        ExpectedStage {
            values: 2560,
            sum: -1.5353805022314191,
            square_sum: 10.156394573002277,
            minimum: -0.357609034,
            maximum: 0.703629017,
        },
        ExpectedStage {
            values: 2560,
            sum: -5.0755788639853563,
            square_sum: 32.196231702024356,
            minimum: -0.437711984,
            maximum: 0.397688746,
        },
        ExpectedStage {
            values: 9728,
            sum: -306.00732190907001,
            square_sum: 801.20636757069406,
            minimum: -1.29935861,
            maximum: 1.65794945,
        },
        ExpectedStage {
            values: 9728,
            sum: -28.947566583752632,
            square_sum: 2384.5605081631452,
            minimum: -2.88478184,
            maximum: 3.10802031,
        },
        ExpectedStage {
            values: 9728,
            sum: 6.7119678670240432,
            square_sum: 110.90022319985215,
            minimum: -2.41801453,
            maximum: 3.94949484,
        },
        ExpectedStage {
            values: 2560,
            sum: 4.5555788837373257,
            square_sum: 115.16906098423276,
            minimum: -2.02871037,
            maximum: 4.29569626,
        },
        ExpectedStage {
            values: 2560,
            sum: 3.020198957528919,
            square_sum: 150.92829508669277,
            minimum: -2.28426409,
            maximum: 4.99932528,
        },
    ],
    [
        ExpectedStage {
            values: 2560,
            sum: 1.8339599370956421,
            square_sum: 1.6299812763549328,
            minimum: -0.0875091553,
            maximum: 0.0864257812,
        },
        ExpectedStage {
            values: 2560,
            sum: 1.9912253356305882,
            square_sum: 2.5928948376853129,
            minimum: -0.213049322,
            maximum: 0.164858878,
        },
        ExpectedStage {
            values: 4096,
            sum: -1.5668587217805907,
            square_sum: 14.44524404726938,
            minimum: -0.430849612,
            maximum: 0.840488374,
        },
        ExpectedStage {
            values: 1024,
            sum: -0.68246974237263203,
            square_sum: 5.0895367727635357,
            minimum: -0.417694509,
            maximum: 0.3535344,
        },
        ExpectedStage {
            values: 1024,
            sum: 0.76482301414944232,
            square_sum: 1.2516115347419401,
            minimum: -0.213199064,
            maximum: 0.261873066,
        },
        ExpectedStage {
            values: 4096,
            sum: -127.2367453168863,
            square_sum: 11124.187021330647,
            minimum: -9.5060215,
            maximum: 9.76912689,
        },
        ExpectedStage {
            values: 1024,
            sum: 108.93006790231448,
            square_sum: 204426.09733016838,
            minimum: -203.384186,
            maximum: 234.150864,
        },
        ExpectedStage {
            values: 4096,
            sum: -86.020639717404265,
            square_sum: 11124.186933757062,
            minimum: -8.72748756,
            maximum: 9.76933575,
        },
        ExpectedStage {
            values: 1024,
            sum: 106.79874930613732,
            square_sum: 204426.10330205943,
            minimum: -203.379929,
            maximum: 234.14711,
        },
        ExpectedStage {
            values: 64,
            sum: 31.999999635881977,
            square_sum: 25.584657911140582,
            minimum: 0.0000257407992,
            maximum: 0.999974251,
        },
        ExpectedStage {
            values: 4096,
            sum: 3.3373512367943476,
            square_sum: 3.9977038514171541,
            minimum: -0.237674534,
            maximum: 0.287151128,
        },
        ExpectedStage {
            values: 2560,
            sum: 2.1096423713024706,
            square_sum: 8.1605826462222435,
            minimum: -0.456063509,
            maximum: 0.817569852,
        },
        ExpectedStage {
            values: 2560,
            sum: 3.9436023156158626,
            square_sum: 10.225721773339018,
            minimum: -0.465619326,
            maximum: 0.805744529,
        },
        ExpectedStage {
            values: 2560,
            sum: 5.6067326574002436,
            square_sum: 31.193671282377256,
            minimum: -0.395954847,
            maximum: 0.516126752,
        },
        ExpectedStage {
            values: 9728,
            sum: -190.13488537073135,
            square_sum: 767.92941151368325,
            minimum: -1.65888,
            maximum: 1.75051165,
        },
        ExpectedStage {
            values: 9728,
            sum: 59.717146830633283,
            square_sum: 2282.2005864727894,
            minimum: -2.54886079,
            maximum: 3.3630197,
        },
        ExpectedStage {
            values: 9728,
            sum: 9.4641116253438327,
            square_sum: 104.48189518060843,
            minimum: -1.9912107,
            maximum: 2.87858701,
        },
        ExpectedStage {
            values: 2560,
            sum: 19.40909420279786,
            square_sum: 73.432780549526612,
            minimum: -1.42676926,
            maximum: 2.22885132,
        },
        ExpectedStage {
            values: 2560,
            sum: 23.352696458809078,
            square_sum: 102.16349271489842,
            minimum: -1.82161164,
            maximum: 3.03459597,
        },
    ],
];
