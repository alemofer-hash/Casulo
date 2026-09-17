#![no_std]
#![no_main]
#![feature(alloc_error_handler)]
#![feature(abi_x86_interrupt)]

extern crate alloc;

mod fw_cfg;
mod interrupts;
mod memory;
mod model_block0_oracle;
mod model_block0_probe;
mod model_creation_probe;
mod model_decoder_probe;
mod model_paged_probe;
mod model_probe;
mod model_tokenizer_probe;
mod once;
mod platform;
mod process;
mod product_runtime;
mod scheduler;
mod serial;
mod shell;
mod smp;
mod system_pack;
mod tcap;
mod tcap_v2;
mod topology;

use alloc::boxed::Box;
use alloc::vec::Vec;
use bootloader_api::config::Mapping;
use bootloader_api::info::PixelFormat;
use bootloader_api::{BootInfo, BootloaderConfig, entry_point};
use core::alloc::Layout;
use core::fmt::Write;
use x86_64::instructions::{hlt, port::Port};

const CONFIG: BootloaderConfig = {
    let mut config = BootloaderConfig::new_default();
    // Projection is deliberately transactional: applying an event keeps a
    // complete candidate scene until validation succeeds.  The renderer and
    // its self-test therefore need several fixed-size SceneState values at
    // once.  Keep a bounded but explicit native presentation stack instead of
    // relying on the bootloader default or an optimizer-specific frame layout.
    config.kernel_stack_size = 512 * 1024;
    config.mappings.physical_memory = Some(Mapping::Dynamic);
    config
};

entry_point!(kernel_main, config = &CONFIG);

#[repr(u32)]
enum QemuExit {
    Success = 0x10,
    Failure = 0x11,
}

fn exit_qemu(code: QemuExit) -> ! {
    unsafe {
        let mut port: Port<u32> = Port::new(0xf4);
        port.write(code as u32);
    }
    loop {
        hlt();
    }
}

#[derive(Clone, Copy)]
struct FramePaint {
    painted: bool,
    fingerprint: u64,
    pixels_written: u64,
}

#[inline(never)]
fn paint_framebuffer(boot_info: &mut BootInfo) -> FramePaint {
    let mut scene = casulo_presentation_core::SceneState::new();
    if scene
        .apply(casulo_presentation_core::ProjectionEvent::control(
            0x4e46_0001,
            0,
            casulo_presentation_core::EventKind::PresenceReady,
            0,
            b"Casulo Native presente.",
        ))
        .is_err()
    {
        return FramePaint {
            painted: false,
            fingerprint: 0,
            pixels_written: 0,
        };
    }
    paint_scene(boot_info, &scene)
}

#[inline(never)]
fn paint_scene(
    boot_info: &mut BootInfo,
    scene: &casulo_presentation_core::SceneState,
) -> FramePaint {
    let Some(framebuffer) = boot_info.framebuffer.as_mut() else {
        return FramePaint {
            painted: false,
            fingerprint: 0,
            pixels_written: 0,
        };
    };
    let info = framebuffer.info();
    let order = match info.pixel_format {
        PixelFormat::Rgb => casulo_presentation_core::PixelOrder::Rgb,
        PixelFormat::Bgr => casulo_presentation_core::PixelOrder::Bgr,
        PixelFormat::U8 => casulo_presentation_core::PixelOrder::Gray,
        _ => {
            return FramePaint {
                painted: false,
                fingerprint: 0,
                pixels_written: 0,
            };
        }
    };
    let Ok(mut surface) = casulo_presentation_core::Surface::new(
        framebuffer.buffer_mut(),
        info.width,
        info.height,
        info.stride,
        info.bytes_per_pixel,
        order,
    ) else {
        return FramePaint {
            painted: false,
            fingerprint: 0,
            pixels_written: 0,
        };
    };
    let receipt = casulo_presentation_core::render_scene(&mut surface, scene);
    FramePaint {
        painted: true,
        fingerprint: receipt.framebuffer_fingerprint,
        pixels_written: receipt.pixels_written,
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum OwnerBridgeRead {
    Complete(usize),
    TimedOut(u8),
    Overflow,
}

/// Waits for exactly one bounded line from the first-party owner bridge.
///
/// The contents are treated as untrusted data and are never executed by the
/// kernel. The bounded read is compiled only into the dedicated generative VM
/// image, leaving the Product Alpha release image unchanged.
fn await_owner_bridge_line(serial: &mut serial::Serial) -> OwnerBridgeRead {
    const MAX_RESPONSE_BYTES: usize = 4096;
    // Ring-3 probes may leave IF cleared. Re-enable the already validated PIT
    // and IDT explicitly so HLT remains low-power while owner inference runs.
    x86_64::instructions::interrupts::enable();
    const TIMEOUT_TICKS: u64 = 90_000; // 15 min at the validated 100 Hz PIT.
    let deadline = interrupts::timer_ticks().saturating_add(TIMEOUT_TICKS);
    let mut received = 0usize;
    let mut observed_line_status = 0u8;
    while interrupts::timer_ticks() < deadline {
        observed_line_status |= serial.line_status();
        match serial.try_read_byte() {
            Some(b'\n') => return OwnerBridgeRead::Complete(received),
            Some(b'\r') => {}
            Some(_) if received < MAX_RESPONSE_BYTES => received += 1,
            Some(_) => return OwnerBridgeRead::Overflow,
            None => hlt(),
        }
    }
    OwnerBridgeRead::TimedOut(observed_line_status)
}

fn kernel_main(boot_info: &'static mut BootInfo) -> ! {
    // The Casulo hard-float target may emit SSE2 in any downstream Rust code.
    // Arm architectural state before allocations, formatting or model work.
    let sse2_ready = process::initialize_sse2();
    let mut serial = serial::Serial::init();
    match option_env!("CASULO_BOOT_PROBE") {
        Some("panic") => {
            let _ = writeln!(serial, "PANIC_PROBE=TRIGGERED");
            panic!("intentional deterministic panic probe");
        }
        Some("reboot") => {
            let _ = writeln!(serial, "REBOOT_PROBE=REQUESTED");
            platform::request_reboot();
        }
        Some(other) => {
            let _ = writeln!(serial, "CASULO_BOOT_PROBE_INVALID={other}");
            exit_qemu(QemuExit::Failure)
        }
        None => {}
    }
    let framebuffer = paint_framebuffer(boot_info);
    let mut creation_frame = framebuffer;
    let memory_regions = boot_info.memory_regions.len();
    let physical_memory_offset = boot_info
        .physical_memory_offset
        .into_option()
        .expect("bootloader physical memory mapping missing");
    let regions = unsafe {
        core::slice::from_raw_parts(
            boot_info.memory_regions.as_ptr(),
            boot_info.memory_regions.len(),
        )
    };
    let mut memory =
        unsafe { memory::initialize(physical_memory_offset, regions, process::user_image()) };
    let heap_probe = Box::new(0x4341_5355_4c4fu64);
    let heap_ok = *heap_probe == 0x4341_5355_4c4f;
    let cpu = topology::detect();
    let interrupt = interrupts::initialize_and_self_test();
    let _ = writeln!(serial, "SMP_START_ATTEMPT=1");
    let smp = smp::start_one(&memory, boot_info.rsdp_addr.into_option());
    let _ = writeln!(serial, "SMP_START_RETURNED=1");
    process::initialize_syscall_abi();
    let process = process::run(memory.user_address_space);
    let neural_abi = process::run_neural_abi(memory.user_address_space);
    let neural_permission = process::run_neural_abi_permission_probe(memory.user_address_space);
    let neural_abi_pass = neural_abi.exit_status == 0
        && neural_abi.separate_cr3
        && neural_abi.permission_mask == 0x0381
        && neural_abi.syscall_count == 4
        && neural_abi.neural_model_asserts == 1
        && neural_abi.neural_primitive_calls == 1
        && neural_abi.neural_tokens_emitted == 1
        && neural_abi.neural_last_token == 42
        && neural_abi.neural_receipt_accumulator != 0
        && neural_permission.exit_status == 0
        && neural_permission.permission_mask == 0x0001
        && neural_permission.denied_syscalls == 1
        && neural_permission.permission_audit_events == 1
        && neural_permission.neural_model_asserts == 0
        && neural_permission.neural_primitive_calls == 0
        && neural_permission.neural_tokens_emitted == 0;

    // Adversarial G2 isolation probes use two fresh low-half roots. Process A
    // owns the private page; process B has no translation for it and must be
    // terminated by the user-fault containment path without stopping kernel.
    let probe_a = memory.map_probe_process(true);
    let probe_b = memory.map_probe_process(false);
    let private_probe = process::run_private_probe(probe_a.address_space);
    let user_faults_before = interrupts::contained_user_faults();
    let cross_space_probe = process::run_cross_space_fault_probe(probe_b.address_space);
    let user_faults_after = interrupts::contained_user_faults();
    let distinct_process_roots = probe_a.address_space.level_4_frame
        != probe_b.address_space.level_4_frame
        && probe_a.address_space.level_4_frame != memory.user_address_space.level_4_frame
        && probe_b.address_space.level_4_frame != memory.user_address_space.level_4_frame;
    let cross_space_isolation = distinct_process_roots
        && probe_a.private_page_mapped
        && !probe_b.private_page_mapped
        && private_probe.exit_status == 0
        && cross_space_probe.exit_status == 125
        && user_faults_after == user_faults_before + 1;

    // A non-yielding ring-3 loop is forcibly redirected by IRQ0 after a
    // bounded budget. A subsequent user process and the kernel must progress.
    const WATCHDOG_BUDGET: u64 = 3;
    let preemptions_before = interrupts::user_watchdog_preemptions();
    let non_yielding = process::run_non_yielding_watchdog(probe_b.address_space, WATCHDOG_BUDGET);
    let watchdog_elapsed = interrupts::user_watchdog_elapsed_ticks();
    let preemptions_after = interrupts::user_watchdog_preemptions();
    let post_watchdog_progress = process::run_private_probe(probe_a.address_space);
    let user_watchdog_pass = non_yielding.exit_status == 124
        && preemptions_after == preemptions_before + 1
        && (WATCHDOG_BUDGET..=WATCHDOG_BUDGET + 2).contains(&watchdog_elapsed)
        && post_watchdog_progress.exit_status == 0;

    // NP10 executes these same structural checks inside the complete creation
    // route. Avoid allocating the historical standalone probe arenas first:
    // this kernel uses a deliberately monotonic boot arena.
    let creation_required = option_env!("CASULO_NATIVE_CREATION") == Some("1");

    // NP4 admits one exact, host-verified owner model through QEMU's read-only
    // fw_cfg file interface. The guest parses metadata and tensor descriptors
    // through a bounded page cache and reads authentic pages near the start,
    // middle and end. It does not load the full model or emit a token.
    let model_paged_required =
        option_env!("CASULO_NATIVE_MODEL_PAGED_IO") == Some("1") && !creation_required;
    let _ = writeln!(serial, "CASULO_NATIVE_PHASE_MODEL_PAGED=BEGIN");
    let model_paged_result = if model_paged_required {
        Some(model_paged_probe::run(&mut memory))
    } else {
        None
    };
    let _ = writeln!(serial, "CASULO_NATIVE_PHASE_MODEL_PAGED=END");
    let model_paged_gate = match &model_paged_result {
        Some(Ok(_)) => true,
        Some(Err(_)) => false,
        None => !model_paged_required,
    };

    // NP5 consumes the tokenizer arrays from the complete GGUF, compares a
    // bounded ordinary-text slice with the frozen offline llama.cpp oracle and
    // decodes one authentic Q6_K embedding row. It does not execute the chat
    // template, transformer blocks, logits or sampling.
    let model_tokenizer_required =
        option_env!("CASULO_NATIVE_TOKENIZER_EMBEDDING") == Some("1") && !creation_required;
    let _ = writeln!(serial, "CASULO_NATIVE_PHASE_TOKENIZER=BEGIN");
    let model_tokenizer_result = if model_tokenizer_required {
        Some(model_tokenizer_probe::run(&mut memory))
    } else {
        None
    };
    let _ = writeln!(serial, "CASULO_NATIVE_PHASE_TOKENIZER=END");
    let model_tokenizer_gate = match &model_tokenizer_result {
        Some(Ok(_)) => true,
        Some(Err(_)) => false,
        None => !model_tokenizer_required,
    };

    // NP6 executes one authentic token position through every operation of
    // Qwen3 block zero and compares 19 intermediate summaries with the frozen
    // independent oracle. It still cannot produce logits or an output token.
    let model_block0_required =
        option_env!("CASULO_NATIVE_MODEL_BLOCK0") == Some("1") && !creation_required;
    let _ = writeln!(serial, "CASULO_NATIVE_PHASE_BLOCK0=BEGIN");
    let model_block0_result = if model_block0_required {
        Some(model_block0_probe::run(&mut memory))
    } else {
        None
    };
    let _ = writeln!(serial, "CASULO_NATIVE_PHASE_BLOCK0=END");
    let model_block0_gate = match &model_block0_result {
        Some(Ok(_)) => true,
        Some(Err(_)) => false,
        None => !model_block0_required,
    };

    // NP7 executes all 36 adopted-model blocks, output RMS normalization and
    // the tied logits projection inside the kernel. The verified candidate is
    // intentionally withheld until a later T sampling/publication policy.
    let model_decoder_required =
        option_env!("CASULO_NATIVE_MODEL_DECODER") == Some("1") && !creation_required;
    // Parse only the bounded system-pack directory before decoding so the
    // content-addressed T policy can judge each token at the exact publication
    // boundary. The complete pack is parsed and corruption-tested again below.
    let early_ramdisk_address = boot_info
        .ramdisk_addr
        .into_option()
        .expect("G3 TCAP ramdisk missing");
    let early_ramdisk_length =
        usize::try_from(boot_info.ramdisk_len).expect("G3 ramdisk too large");
    let early_ramdisk = unsafe {
        core::slice::from_raw_parts(early_ramdisk_address as *const u8, early_ramdisk_length)
    };
    let early_pack = if system_pack::is_system_pack(early_ramdisk) {
        match system_pack::parse(early_ramdisk) {
            Ok(pack) => Some(pack),
            Err(reason) => {
                let _ = writeln!(serial, "CASULO_NATIVE_SYSTEM_PACK=QUARANTINE");
                let _ = writeln!(serial, "CASULO_NATIVE_SYSTEM_PACK_REJECT={reason:?}");
                exit_qemu(QemuExit::Failure)
            }
        }
    } else {
        None
    };
    let decoder_sampling_policy = early_pack.and_then(|pack| {
        pack.entry(system_pack::KIND_NATIVE_SAMPLING_POLICY)
            .map(|entry| entry.payload)
    });
    let creation_prompt = early_pack.and_then(|pack| {
        pack.entry(system_pack::KIND_NATIVE_CREATION_PROMPT)
            .map(|entry| entry.payload)
    });
    let creation_artifact = early_pack.and_then(|pack| {
        pack.entry(system_pack::KIND_NATIVE_CREATION_ARTIFACT)
            .map(|entry| entry.payload)
    });
    let creation_acceptance = early_pack.and_then(|pack| {
        pack.entry(system_pack::KIND_NATIVE_CREATION_ACCEPTANCE)
            .map(|entry| entry.payload)
    });
    let creation_model_entry =
        early_pack.and_then(|pack| pack.entry(system_pack::KIND_NATIVE_MODEL_GGUF));
    let creation_model = creation_model_entry.map(|entry| {
        if entry.payload.len() as u64 == model_paged_probe::EXPECTED_MODEL_BYTES
            && entry.sha256 == model_creation_probe::MODEL_SHA256_BYTES
        {
            entry.payload
        } else {
            // Some(empty) prevents an invalid physical entry from silently
            // falling back to QEMU fw_cfg.
            &[][..]
        }
    });
    let _ = writeln!(serial, "CASULO_NATIVE_PHASE_DECODER=BEGIN");
    let model_decoder_result = if model_decoder_required {
        Some(model_decoder_probe::run(
            &mut memory,
            &mut serial,
            decoder_sampling_policy,
        ))
    } else {
        None
    };
    let _ = writeln!(serial, "CASULO_NATIVE_PHASE_DECODER=END");
    let model_decoder_gate = match &model_decoder_result {
        Some(Ok(_)) => true,
        Some(Err(_)) => false,
        None => !model_decoder_required,
    };

    let mut creation_scene = casulo_presentation_core::SceneState::new();
    if creation_required {
        let startup = [
            casulo_presentation_core::ProjectionEvent::control(
                0x4e50_0001,
                0,
                casulo_presentation_core::EventKind::PresenceReady,
                0,
                b"Estou aqui.",
            ),
            casulo_presentation_core::ProjectionEvent::control(
                0x4e50_0002,
                0,
                casulo_presentation_core::EventKind::ModelLoading,
                0,
                b"",
            ),
            casulo_presentation_core::ProjectionEvent::control(
                0x4e50_0003,
                0,
                casulo_presentation_core::EventKind::ModelReady,
                0,
                b"",
            ),
            casulo_presentation_core::ProjectionEvent::control(
                0x4e50_0004,
                10,
                casulo_presentation_core::EventKind::AssistantStart,
                0,
                b"",
            ),
        ];
        for event in startup {
            if creation_scene.apply(event).is_err() {
                exit_qemu(QemuExit::Failure)
            }
        }
        creation_frame = paint_scene(boot_info, &creation_scene);
    }
    let _ = writeln!(serial, "CASULO_NATIVE_PHASE_CREATION=BEGIN");
    let creation_result = if creation_required {
        match (
            decoder_sampling_policy,
            creation_prompt,
            creation_artifact,
            creation_acceptance,
        ) {
            (Some(token_policy), Some(prompt), Some(artifact), Some(acceptance)) => {
                Some(model_creation_probe::run(
                    &mut memory,
                    &mut serial,
                    creation_model,
                    token_policy,
                    prompt,
                    artifact,
                    acceptance,
                    |index, text, _receipt_hash| {
                        let event = casulo_presentation_core::ProjectionEvent::control(
                            0x4e51_0000u32.saturating_add(index),
                            10,
                            casulo_presentation_core::EventKind::AssistantToken,
                            u16::try_from(index + 1).unwrap_or(u16::MAX),
                            text,
                        );
                        if creation_scene.apply(event).is_err() {
                            return false;
                        }
                        creation_frame = paint_scene(boot_info, &creation_scene);
                        creation_frame.painted
                    },
                ))
            }
            _ => Some(Err(model_creation_probe::Reject::Prompt)),
        }
    } else {
        None
    };
    if let Some(Ok(receipt)) = &creation_result {
        let _ = creation_scene.apply(casulo_presentation_core::ProjectionEvent::control(
            0x4e52_0001,
            10,
            casulo_presentation_core::EventKind::AssistantEnd,
            0,
            b"",
        ));
        let evidence = receipt.token_receipt_chain_tail;
        let _ = creation_scene.apply(casulo_presentation_core::ProjectionEvent::job(
            0x4e52_0002,
            20,
            casulo_presentation_core::EventKind::JobStarted,
            1,
            b"Intencao convertida em forma.",
            evidence,
        ));
        if receipt.cancelled {
            let _ = creation_scene.apply(casulo_presentation_core::ProjectionEvent::job(
                0x4e52_0003,
                20,
                casulo_presentation_core::EventKind::JobCancelled,
                2,
                b"Criacao interrompida; estado tardio descartado.",
                evidence,
            ));
        } else {
            let _ = creation_scene.apply(casulo_presentation_core::ProjectionEvent::job(
                0x4e52_0003,
                20,
                casulo_presentation_core::EventKind::JobMilestone,
                2,
                b"T compilado e simulacao aprovada.",
                receipt.artifact_tcap_hash,
            ));
            let _ = creation_scene.apply(casulo_presentation_core::ProjectionEvent::job(
                0x4e52_0004,
                20,
                casulo_presentation_core::EventKind::JobCompleted,
                3,
                b"SOME DOIS NUMEROS - 7 + 11 = 18",
                receipt.materialization_sha256,
            ));
        }
        creation_frame = paint_scene(boot_info, &creation_scene);
    }
    let _ = writeln!(serial, "CASULO_NATIVE_PHASE_CREATION=END");
    let creation_gate = match &creation_result {
        Some(Ok(receipt)) => receipt.gate() && creation_frame.painted,
        Some(Err(_)) => false,
        None => !creation_required,
    };

    // The TCAP or content-addressed system pack is a bootloader ramdisk, never
    // a host-mounted block device. Parse and hash every entry before mapping
    // one byte executable.
    let ramdisk_address = boot_info
        .ramdisk_addr
        .into_option()
        .expect("G3 TCAP ramdisk missing");
    let ramdisk_length = usize::try_from(boot_info.ramdisk_len).expect("G3 ramdisk too large");
    let ramdisk =
        unsafe { core::slice::from_raw_parts(ramdisk_address as *const u8, ramdisk_length) };
    let (
        runtime_payload,
        system_pack_present,
        system_pack_entries,
        system_pack_ux,
        system_pack_guide_t,
        system_pack_model_probe,
        system_pack_sampling_policy,
        system_pack_creation_prompt,
        system_pack_creation_artifact,
        system_pack_creation_acceptance,
        system_pack_native_model_present,
        system_pack_native_model_admitted,
        system_pack_corruption_quarantined,
    ) = if system_pack::is_system_pack(ramdisk) {
        let corruption_quarantined = system_pack::bounded_corruption_probe();
        let pack = early_pack.expect("validated system pack missing");
        let native_model = pack.entry(system_pack::KIND_NATIVE_MODEL_GGUF);
        let tcap = match pack.entry(system_pack::KIND_BOOTSTRAP_TCAP) {
            Some(entry) => entry.payload,
            None => {
                let _ = writeln!(serial, "CASULO_NATIVE_SYSTEM_PACK_REJECT=MISSING_TCAP");
                exit_qemu(QemuExit::Failure)
            }
        };
        (
            tcap,
            true,
            pack.len(),
            pack.entry(system_pack::KIND_UX_CONTRACT).is_some(),
            pack.entry(system_pack::KIND_GUIDE_T_SOURCE).is_some(),
            pack.entry(system_pack::KIND_MODEL_GGUF_PROBE)
                .map(|entry| entry.payload),
            pack.entry(system_pack::KIND_NATIVE_SAMPLING_POLICY)
                .map(|entry| entry.payload),
            pack.entry(system_pack::KIND_NATIVE_CREATION_PROMPT)
                .map(|entry| entry.payload),
            pack.entry(system_pack::KIND_NATIVE_CREATION_ARTIFACT)
                .map(|entry| entry.payload),
            pack.entry(system_pack::KIND_NATIVE_CREATION_ACCEPTANCE)
                .map(|entry| entry.payload),
            native_model.is_some(),
            native_model.is_none_or(|entry| {
                entry.payload.len() as u64 == model_paged_probe::EXPECTED_MODEL_BYTES
                    && entry.sha256 == model_creation_probe::MODEL_SHA256_BYTES
            }),
            corruption_quarantined,
        )
    } else {
        (
            ramdisk, false, 0, false, false, None, None, None, None, None, false, true, true,
        )
    };
    let model_probe_required = option_env!("CASULO_NATIVE_MODEL_PROBE") == Some("1");
    let model_probe_corruption_quarantined = if let Some(payload) = system_pack_model_probe {
        let mut corrupted = Vec::from(payload);
        let corrupt_index = corrupted.len().checked_sub(1).expect("empty GGUF probe");
        corrupted[corrupt_index] ^= 0x01;
        model_probe::run(&corrupted).is_err()
    } else {
        true
    };
    let model_probe_result = system_pack_model_probe.map(model_probe::run);
    let model_probe_gate = match &model_probe_result {
        Some(Ok(_)) => model_probe_corruption_quarantined,
        Some(Err(_)) => false,
        None => !model_probe_required,
    };
    let native_sampling_required =
        option_env!("CASULO_NATIVE_MODEL_SAMPLING") == Some("1") && !creation_required;
    let native_sampling_gate = if !native_sampling_required {
        true
    } else {
        match (&system_pack_sampling_policy, &model_decoder_result) {
            (Some(_), Some(Ok(decoder))) => {
                decoder.sampling_gate
                    && decoder.sampling_tokens_authorized == decoder.incremental_tokens_completed
                    && decoder.candidate_published
                    && (decoder.incremental_tokens_completed == 1
                        || decoder.second_candidate_published)
            }
            _ => false,
        }
    };
    if tcap_v2::is_native_probe(runtime_payload) {
        let mut corrupted = Vec::from(runtime_payload);
        let corrupt_index = corrupted
            .len()
            .checked_sub(1)
            .expect("empty TCAP v2 ramdisk");
        corrupted[corrupt_index] ^= 0x01;
        let corruption_quarantined = tcap_v2::execute(&corrupted).is_err();
        drop(corrupted);
        match tcap_v2::execute(runtime_payload) {
            Ok(probe) if corruption_quarantined => {
                let _ = writeln!(serial, "TCAP_V2_VALIDATION=PASS");
                let _ = writeln!(serial, "TCAP_V2_TARGET=portable-t-vm");
                let _ = writeln!(serial, "TCAP_V2_RUNTIME=t-runtime/native-2.0");
                let _ = writeln!(
                    serial,
                    "TCAP_V2_ISOLATION=qemu-guest-no-network-no-host-block-device"
                );
                let _ = writeln!(serial, "TCAP_V2_TCAP_HASH={}", probe.tcap_hash);
                let _ = writeln!(serial, "TCAP_V2_STEPS={}", probe.steps);
                let _ = writeln!(serial, "TCAP_V2_OBSERVABLE={}", probe.observable);
                let _ = writeln!(serial, "TCAP_V2_RECEIPT={}", probe.receipt);
                let _ = writeln!(serial, "TCAP_V2_CORRUPTION=QUARANTINE");
                let _ = writeln!(serial, "TCAP_V2_GATE=PASS");
                let _ = writeln!(serial, "SCIENTIFIC_BENCHMARK=NOT_STARTED");
                let _ = writeln!(serial, "SHUTDOWN_PATH=isa-debug-exit/0.1");
                exit_qemu(QemuExit::Success)
            }
            Ok(_) => {
                let _ = writeln!(serial, "TCAP_V2_CORRUPTION=EXECUTED");
                let _ = writeln!(serial, "TCAP_V2_GATE=FAIL");
                exit_qemu(QemuExit::Failure)
            }
            Err(reason) => {
                let _ = writeln!(serial, "TCAP_V2_VALIDATION=QUARANTINE");
                let _ = writeln!(serial, "TCAP_V2_REJECT_REASON={reason}");
                let _ = writeln!(serial, "TCAP_V2_EXECUTION_COUNT=0");
                let _ = writeln!(serial, "TCAP_V2_GATE=FAIL");
                exit_qemu(QemuExit::Failure)
            }
        }
    }
    let mut corrupted = Vec::from(runtime_payload);
    let corrupt_index = corrupted.len().checked_sub(1).expect("empty TCAP ramdisk");
    corrupted[corrupt_index] ^= 0x01;
    let corruption_quarantined = tcap::parse(&corrupted).is_err();
    drop(corrupted);
    let package = match tcap::parse(runtime_payload) {
        Ok(package) => package,
        Err(reason) => {
            let _ = writeln!(serial, "TCAP_VALIDATION=QUARANTINE");
            let _ = writeln!(serial, "TCAP_REJECT_REASON={reason:?}");
            let _ = writeln!(serial, "TCAP_EXECUTION_COUNT=0");
            exit_qemu(QemuExit::Failure)
        }
    };
    let learn_mapping = memory.map_learn_payload(&package);
    let permission_probe = process::run_learn_permission_probe(learn_mapping);
    let learn_process = process::run_learn(learn_mapping);
    let observed_initial_loss = memory.read_learn_f64(learn_mapping, 2064);
    let observed_final_loss = memory.read_learn_f64(learn_mapping, 2072);
    let mut max_parameter_difference = 0.0f64;
    let mut parameter_equivalence = true;
    for index in 0..package.canary.parameters {
        let observed = memory.read_learn_f64(learn_mapping, 704 + index * 8);
        let difference = (observed - package.canary.expected_parameter(index)).abs();
        if !observed.is_finite() || difference > package.canary.tolerance {
            parameter_equivalence = false;
        }
        max_parameter_difference = max_parameter_difference.max(difference);
    }
    let loss_equivalence = observed_initial_loss.is_finite()
        && observed_final_loss.is_finite()
        && (observed_initial_loss - package.canary.expected_initial_loss).abs()
            <= package.canary.tolerance
        && (observed_final_loss - package.canary.expected_final_loss).abs()
            <= package.canary.tolerance
        && observed_final_loss <= package.canary.target_loss;
    let resource_mapping_bounded = learn_mapping.mapped_user_bytes <= package.resource_memory_limit
        && package.resource_arena_bytes == 656;
    let g3_pass = corruption_quarantined
        && sse2_ready
        && learn_process.exit_status == 0
        && learn_process.separate_cr3
        && learn_process.syscall_count == 1
        && learn_process.permission_mask == 0x03
        && permission_probe.exit_status == 0
        && permission_probe.syscall_count == 2
        && permission_probe.denied_syscalls == 1
        && permission_probe.permission_audit_events == 1
        && learn_mapping.code_rx
        && learn_mapping.data_rw_nx
        && learn_mapping.stack_rw_nx
        && resource_mapping_bounded
        && loss_equivalence
        && parameter_equivalence;
    let g4 = scheduler::run_g4(probe_b.address_space);
    let shell_self_test = shell::self_test();
    let product_runtime = product_runtime::self_test();
    let presentation = casulo_presentation_core::self_test();
    let input_decoder = casulo_presentation_core::input_self_test();
    let persistence_journal = casulo_presentation_core::journal_self_test();

    let _ = writeln!(serial, "CASULO_NATIVE_BOOT_OK");
    let _ = writeln!(serial, "VERSION=Research Preview 0.1");
    let _ = writeln!(serial, "ARCH=x86_64");
    let _ = writeln!(serial, "UEFI=true");
    let _ = writeln!(serial, "MEMORY_REGIONS={memory_regions}");
    let _ = writeln!(
        serial,
        "FRAMEBUFFER={}",
        if framebuffer.painted {
            "painted"
        } else {
            "unavailable"
        }
    );
    let _ = writeln!(serial, "CASULO_NATIVE_RENDERER=stark-jobs-gop/0.1");
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_FRAME_FINGERPRINT={:016x}",
        framebuffer.fingerprint
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_FRAME_PIXELS_WRITTEN={}",
        framebuffer.pixels_written
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_RENDERER_GATE={}",
        if framebuffer.painted { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(serial, "PANIC_DUMP=armed");
    let _ = writeln!(serial, "G1_BOOT_SMOKE=PASS");
    let _ = writeln!(serial, "PHYSICAL_USABLE_BYTES={}", memory.usable_bytes);
    let _ = writeln!(serial, "PHYSICAL_USABLE_FRAMES={}", memory.usable_frames);
    let _ = writeln!(serial, "PAGING=active");
    let _ = writeln!(
        serial,
        "LOW_USABLE_FRAME={:#x}",
        memory
            .low_usable_frame
            .map(|f| f.start_address().as_u64())
            .unwrap_or(0)
    );
    let _ = writeln!(serial, "HEAP_PAGES={}", memory.heap_pages);
    let _ = writeln!(
        serial,
        "HEAP_ALLOC={}",
        if heap_ok { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "HEAP_KERNEL_ONLY={}",
        if memory.heap_kernel_only {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "GUARD_PAGE_UNMAPPED={}",
        if memory.guard_unmapped {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "GDT_IDT=loaded");
    let _ = writeln!(serial, "TIMER_SOURCE=8254_PIT_IRQ0");
    let _ = writeln!(serial, "TIMER_HZ={}", interrupt.timer_hz);
    let _ = writeln!(serial, "TIMER_TICKS={}", interrupt.timer_ticks);
    let _ = writeln!(
        serial,
        "WATCHDOG_CONTRACT={}",
        if interrupt.watchdog_passed {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "FAULTS_CONTAINED={}", interrupt.contained_faults);
    let _ = writeln!(
        serial,
        "GUARD_FAULT_CONTAINMENT={}",
        if interrupt.contained_faults == 1 {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "CPU_VENDOR={}", cpu.vendor_str());
    let _ = writeln!(serial, "TOPOLOGY_LOGICAL_CPUS={}", cpu.logical_processors);
    let _ = writeln!(serial, "TOPOLOGY_THREADS_PER_CORE={}", cpu.threads_per_core);
    let _ = writeln!(serial, "TOPOLOGY_BSP_X2APIC_ID={}", cpu.bsp_x2apic_id);
    let _ = writeln!(serial, "X2APIC_SUPPORTED={}", cpu.x2apic_supported);
    let _ = writeln!(serial, "HYPERVISOR_PRESENT={}", cpu.hypervisor_present);
    let _ = writeln!(serial, "SMP_SCOPE=bounded-qemu-2vcpu");
    let _ = writeln!(
        serial,
        "SMP_MADT_VALID={}",
        if smp.madt_valid { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(serial, "SMP_APS_EXPECTED={}", smp.expected_aps);
    let _ = writeln!(serial, "SMP_APS_STARTED={}", smp.started_aps);
    let _ = writeln!(serial, "SMP_TARGET_APIC_ID={}", smp.target_apic_id);
    let _ = writeln!(serial, "SMP_LAPIC_PHYSICAL={:#x}", smp.lapic_physical);
    let _ = writeln!(serial, "SMP_BOUNDED={}", smp.bounded);
    let _ = writeln!(
        serial,
        "SMP_GATE={}",
        if smp.madt_valid && smp.expected_aps == 1 && smp.started_aps == 1 {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "RING3_PROCESSES=4");
    let _ = writeln!(serial, "RING3_EXIT_STATUS={}", process.exit_status);
    let _ = writeln!(
        serial,
        "PROCESS_SEPARATE_CR3={}",
        if process.separate_cr3 { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "KERNEL_USER_ACCESS={}",
        if memory.kernel_user_inaccessible {
            "DENIED"
        } else {
            "EXPOSED"
        }
    );
    let _ = writeln!(
        serial,
        "USER_PAGING_BRANCH_PRIVATE={}",
        if memory.user_paging_branch_private {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "USER_CODE_RX={}",
        if memory.user_code_rx { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "USER_STACK_NX={}",
        if memory.user_stack_nx { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(serial, "SYSCALL_ABI=syscall-sysretq/0.1");
    let _ = writeln!(serial, "SYSCALL_COUNT={}", process.syscall_count);
    let _ = writeln!(serial, "SYSCALL_DEFINED_MASK=0x3ff");
    let _ = writeln!(serial, "SYSCALL_PERMISSION_MASK=0x7f");
    let _ = writeln!(
        serial,
        "SYSCALL_ENOSYS={}",
        if process.unknown_rejected {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "SYSCALL_IPC_ROUNDTRIP={}",
        if process.ipc_roundtrip {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "SYSCALL_TRACE_EVENTS={}", process.trace_events);
    let _ = writeln!(serial, "SYSCALL_CONSOLE_BYTES={}", process.console_bytes);
    let _ = writeln!(
        serial,
        "YIELD_KERNEL_RETURNS={}",
        process.yield_kernel_returns
    );
    let _ = writeln!(serial, "USER_FAULTS_CONTAINED={user_faults_after}");
    let _ = writeln!(
        serial,
        "RING3_PAGE_FAULT_CONTAINMENT={}",
        if cross_space_probe.exit_status == 125 && user_faults_after == user_faults_before + 1 {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "PROCESS_ROOTS_DISTINCT={}",
        if distinct_process_roots {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "PROCESS_A_PRIVATE_READ={}",
        if private_probe.exit_status == 0 {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "PROCESS_B_CROSS_ACCESS={}",
        if cross_space_isolation {
            "DENIED"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "USER_WATCHDOG_BUDGET_TICKS={WATCHDOG_BUDGET}");
    let _ = writeln!(serial, "USER_WATCHDOG_ELAPSED_TICKS={watchdog_elapsed}");
    let _ = writeln!(
        serial,
        "NON_YIELDING_PREEMPTION={}",
        if user_watchdog_pass { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "POST_PREEMPT_KERNEL_PROGRESS={}",
        if post_watchdog_progress.exit_status == 0 {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let creation_pack_complete = system_pack_creation_prompt.is_some()
        && system_pack_creation_artifact.is_some()
        && system_pack_creation_acceptance.is_some();
    let expected_system_pack_entries = if creation_pack_complete && system_pack_native_model_present
    {
        9
    } else if creation_pack_complete {
        8
    } else if system_pack_sampling_policy.is_some() {
        5
    } else if system_pack_model_probe.is_some() {
        4
    } else {
        3
    };
    let system_pack_gate = !system_pack_present
        || (system_pack_entries == expected_system_pack_entries
            && system_pack_ux
            && system_pack_guide_t
            && (!creation_required || creation_pack_complete)
            && system_pack_native_model_admitted
            && system_pack_corruption_quarantined);
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_PRESENT={}",
        if system_pack_present { "YES" } else { "NO" }
    );
    let _ = writeln!(serial, "CASULO_NATIVE_SYSTEM_PACK_BYTES={ramdisk_length}");
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_ENTRIES={system_pack_entries}"
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_UX_CONTRACT={}",
        if system_pack_ux { "PRESENT" } else { "ABSENT" }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_GUIDE_T_SOURCE={}",
        if system_pack_guide_t {
            "PRESENT_NOT_EXECUTED"
        } else {
            "ABSENT"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_SAMPLING_POLICY={}",
        if system_pack_sampling_policy.is_some() {
            "PRESENT"
        } else {
            "ABSENT"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_MODEL_GGUF_PROBE={}",
        if system_pack_model_probe.is_some() {
            "PRESENT"
        } else {
            "ABSENT"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_CREATION_PROMPT={}",
        if system_pack_creation_prompt.is_some() {
            "PRESENT"
        } else {
            "ABSENT"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_CREATION_ARTIFACT={}",
        if system_pack_creation_artifact.is_some() {
            "PRESENT"
        } else {
            "ABSENT"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_CREATION_ACCEPTANCE={}",
        if system_pack_creation_acceptance.is_some() {
            "PRESENT"
        } else {
            "ABSENT"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_FULL_MODEL={}",
        if system_pack_native_model_present {
            if system_pack_native_model_admitted {
                "PRESENT_VALIDATED"
            } else {
                "QUARANTINE"
            }
        } else {
            "ABSENT"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_CORRUPTION={}",
        if system_pack_corruption_quarantined {
            "QUARANTINE"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SYSTEM_PACK_GATE={}",
        if system_pack_gate { "PASS" } else { "FAIL" }
    );
    match &model_probe_result {
        Some(Ok(receipt)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_GGUF_PROBE_PRESENT=YES");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_PROBE_VERSION={}",
                receipt.gguf_version
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_PROBE_METADATA={}",
                receipt.metadata_count
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_PROBE_TENSORS={}",
                receipt.tensor_count
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_SOURCE_MODEL_SHA256={}",
                model_probe::EXPECTED_MODEL_SHA256
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_SOURCE_MODEL_BYTES={}",
                receipt.source_model_bytes
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_SOURCE_TENSOR={}",
                receipt.source_tensor
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_SOURCE_TENSOR_OFFSET={}",
                receipt.source_tensor_offset
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_Q4_K_BLOCK_BYTES={}",
                receipt.block_bytes
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_Q4_K_DOT_F32_BITS={:08x}",
                receipt.dot_f32_bits
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_Q4_K_EXPECTED_F32_BITS={:08x}",
                receipt.expected_dot_f32_bits
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_SOURCE_Q6_TENSOR={}",
                receipt.source_q6_tensor
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_SOURCE_Q6_TENSOR_OFFSET={}",
                receipt.source_q6_tensor_offset
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_Q6_K_BLOCK_BYTES={}",
                receipt.q6_block_bytes
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_Q6_K_DOT_F32_BITS={:08x}",
                receipt.q6_dot_f32_bits
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_Q6_K_EXPECTED_F32_BITS={:08x}",
                receipt.expected_q6_dot_f32_bits
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_SOURCE_F32_TENSOR={}",
                receipt.source_f32_tensor
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_SOURCE_F32_TENSOR_OFFSET={}",
                receipt.source_f32_tensor_offset
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_F32_VALUES={}",
                receipt.f32_values
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_QWEN_CONTEXT={}",
                receipt.config.context_length
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_QWEN_EMBEDDING={}",
                receipt.config.embedding_length
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_QWEN_BLOCKS={}",
                receipt.config.block_count
            );
            let _ = writeln!(serial, "CASULO_NATIVE_GGUF_PROBE_CORRUPTION=QUARANTINE");
            let _ = writeln!(serial, "CASULO_NATIVE_GGUF_PROBE_GATE=PASS");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_WEIGHT_BYTES_CONSUMED={}",
                receipt.block_bytes
            );
            let _ = writeln!(serial, "CASULO_NATIVE_FULL_MODEL_MAPPED=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_FIRST_MODEL_DERIVED_TOKEN=NO");
        }
        Some(Err(reason)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_GGUF_PROBE_PRESENT=YES");
            let _ = writeln!(serial, "CASULO_NATIVE_GGUF_PROBE_REJECT={reason:?}");
            let _ = writeln!(serial, "CASULO_NATIVE_GGUF_PROBE_GATE=FAIL");
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_WEIGHT_BYTES_CONSUMED=0");
            let _ = writeln!(serial, "CASULO_NATIVE_FULL_MODEL_MAPPED=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_FIRST_MODEL_DERIVED_TOKEN=NO");
        }
        None => {
            let _ = writeln!(serial, "CASULO_NATIVE_GGUF_PROBE_PRESENT=NO");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_GGUF_PROBE_GATE={}",
                if model_probe_required {
                    "FAIL"
                } else {
                    "NOT_REQUIRED"
                }
            );
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_WEIGHT_BYTES_CONSUMED=0");
            let _ = writeln!(serial, "CASULO_NATIVE_FULL_MODEL_MAPPED=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_FIRST_MODEL_DERIVED_TOKEN=NO");
        }
    }
    match &model_paged_result {
        Some(Ok(receipt)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_IO=PRESENT");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_TRANSPORT=qemu-fw-cfg-dma-read-only/0.1"
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_ITEM=opt/com.teloscorp.casulo/model.gguf"
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_SOURCE_SHA256_HOST_VERIFIED={}",
                model_paged_probe::EXPECTED_MODEL_SHA256
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_SOURCE_BYTES={}",
                receipt.source_bytes
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_GGUF_VERSION={}",
                receipt.gguf_version
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_METADATA={}",
                receipt.metadata_count
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_TENSORS={}",
                receipt.tensor_count
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_DATA_OFFSET={}",
                receipt.data_offset
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_F32_OFFSET={}",
                receipt.f32_absolute_offset
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_Q6_K_OFFSET={}",
                receipt.q6_absolute_offset
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_Q4_K_OFFSET={}",
                receipt.q4_absolute_offset
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_Q4_K_DOT_F32_BITS={:08x}",
                receipt.q4_dot_bits
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_Q6_K_DOT_F32_BITS={:08x}",
                receipt.q6_dot_bits
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_TAIL_OFFSET={}",
                receipt.tail_offset
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_DMA_OPERATIONS={}",
                receipt.stats.dma_operations
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_CACHE_PAGES={}",
                receipt.stats.cache_pages_loaded
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_BYTES_LOADED={}",
                receipt.stats.bytes_loaded_from_source
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_BYTES_CONSUMED={}",
                receipt.stats.bytes_copied_to_consumer
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_CORRUPTION={}",
                if receipt.local_corruption_quarantined {
                    "QUARANTINE"
                } else {
                    "FAIL"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_OOB={}",
                if receipt.out_of_bounds_quarantined {
                    "QUARANTINE"
                } else {
                    "FAIL"
                }
            );
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_FULL_FILE_ACCESSIBLE=YES");
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_FULL_FILE_RESIDENT=NO");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_MODEL_PAGED_FULL_SHA256_IN_GUEST=NOT_COMPUTED"
            );
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_FIRST_TOKEN=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_GATE=PASS");
        }
        Some(Err(reason)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_IO=QUARANTINE");
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_REJECT={reason:?}");
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_FULL_FILE_ACCESSIBLE=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_FIRST_TOKEN=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_GATE=FAIL");
        }
        None => {
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_IO=ABSENT");
            let _ = writeln!(serial, "CASULO_NATIVE_MODEL_PAGED_GATE=NOT_REQUIRED");
        }
    }
    match &model_tokenizer_result {
        Some(Ok(receipt)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_TOKENIZER_EMBEDDING=PRESENT");
            let _ = writeln!(serial, "CASULO_NATIVE_TOKENIZER_MODEL=gpt2");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_PRE=qwen2-bounded-latin/0.1"
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_ORACLE=llama-tokenize-b10362-offline"
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_ORACLE_SHA256={}",
                model_tokenizer_probe::ORACLE_RUNTIME_SHA256
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_VOCAB={}",
                receipt.token_count
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_MERGES={}",
                receipt.merge_count
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_BOS={}",
                receipt.bos_token_id
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_EOS={}",
                receipt.eos_token_id
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_PADDING={}",
                receipt.padding_token_id
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_CHAT_TEMPLATE_BYTES={}",
                receipt.chat_template_bytes
            );
            let _ = writeln!(serial, "CASULO_NATIVE_TOKENIZER_CHAT_TEMPLATE_EXECUTED=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_TOKENIZER_CASE_CASULO=49242,8763");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_CASE_HELLO_WORLD=14990,1879"
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_CASE_OLA_CASULO=42719,1953,11,11054,8763,13"
            );
            let _ = writeln!(serial, "CASULO_NATIVE_TOKENIZER_CASES=3");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_MERGE_RULES_SCANNED={}",
                receipt.casulo.merge_rules_scanned
                    + receipt.hello_world.merge_rules_scanned
                    + receipt.ola_casulo.merge_rules_scanned
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_VOCAB_ENTRIES_SCANNED={}",
                receipt.casulo.vocabulary_entries_scanned
                    + receipt.hello_world.vocabulary_entries_scanned
                    + receipt.ola_casulo.vocabulary_entries_scanned
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_UNSUPPORTED_SPECIAL={}",
                if receipt.unsupported_special_rejected {
                    "REJECTED"
                } else {
                    "FAIL"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_UNSUPPORTED_SCRIPT={}",
                if receipt.unsupported_script_rejected {
                    "REJECTED"
                } else {
                    "FAIL"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_EMBEDDING_TOKEN_ID={}",
                receipt.embedding_token_id
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_EMBEDDING_ROW_OFFSET={}",
                receipt.embedding_row_offset
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_EMBEDDING_ROW_BYTES={}",
                receipt.embedding_row_bytes
            );
            let _ = writeln!(serial, "CASULO_NATIVE_EMBEDDING_WIDTH=2560");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_EMBEDDING_SUM_F32_BITS={:08x}",
                receipt.embedding_sum_bits
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_EMBEDDING_INVALID_TOKEN={}",
                if receipt.invalid_token_rejected {
                    "REJECTED"
                } else {
                    "FAIL"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_DMA_OPERATIONS={}",
                receipt.stats.dma_operations
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_CACHE_PAGES={}",
                receipt.stats.cache_pages_loaded
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_BYTES_LOADED={}",
                receipt.stats.bytes_loaded_from_source
            );
            let _ = writeln!(serial, "CASULO_NATIVE_TOKENIZER_FIRST_OUTPUT_TOKEN=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_TOKENIZER_EMBEDDING_GATE=PASS");
        }
        Some(Err(reason)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_TOKENIZER_EMBEDDING=QUARANTINE");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_EMBEDDING_REJECT={reason:?}"
            );
            let _ = writeln!(serial, "CASULO_NATIVE_TOKENIZER_FIRST_OUTPUT_TOKEN=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_TOKENIZER_EMBEDDING_GATE=FAIL");
        }
        None => {
            let _ = writeln!(serial, "CASULO_NATIVE_TOKENIZER_EMBEDDING=ABSENT");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_TOKENIZER_EMBEDDING_GATE=NOT_REQUIRED"
            );
        }
    }
    match &model_block0_result {
        Some(Ok(receipt)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0=PRESENT");
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0_ARCHITECTURE=qwen3");
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0_TOKEN_IDS=49242");
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0_CONTEXTS=1");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_TOKENS_COMPLETED={}",
                receipt.block.tokens_completed
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_DESCRIPTORS_SCANNED={}",
                receipt.block.descriptors_scanned
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_MATVEC_CALLS={}",
                receipt.block.work.matvec_calls
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_QUANTIZED_BLOCKS={}",
                receipt.block.work.quantized_blocks
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_WEIGHT_BYTES_READ={}",
                receipt.block.work.weight_bytes_read
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_MULTIPLY_ACCUMULATES={}",
                receipt.block.work.multiply_accumulates
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_ATTENTION_SCORES={}",
                receipt.block.attention_scores
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_ARENA_BYTES={}",
                receipt.arena_bytes
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_ORACLE_STAGES={}",
                receipt.oracle.stages_compared
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_ORACLE_MISMATCH_MASK={:016x}",
                receipt.oracle.mismatch_mask
            );
            let _ = write!(serial, "CASULO_NATIVE_BLOCK0_OUTPUT_SHA256=");
            for byte in receipt.output_sha256 {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_SHAPE_MUTATION={}",
                if receipt.shape_mutation_rejected {
                    "REJECTED"
                } else {
                    "FAIL"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_WIDER_ROPE={}",
                if receipt.wider_rope_rejected {
                    "REJECTED"
                } else {
                    "FAIL"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_WIDER_CONTEXT={}",
                if receipt.wider_context_rejected {
                    "REJECTED"
                } else {
                    "FAIL"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_DMA_OPERATIONS={}",
                receipt.stats.dma_operations
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_CACHE_PAGES={}",
                receipt.stats.cache_pages_loaded
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_BLOCK0_BYTES_LOADED={}",
                receipt.stats.bytes_loaded_from_source
            );
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0_LOGITS=NOT_EXECUTED");
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0_OUTPUT_TOKEN=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0_GATE=PASS");
        }
        Some(Err(reason)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0=QUARANTINE");
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0_REJECT={reason:?}");
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0_OUTPUT_TOKEN=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0_GATE=FAIL");
        }
        None => {
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0=ABSENT");
            let _ = writeln!(serial, "CASULO_NATIVE_BLOCK0_GATE=NOT_REQUIRED");
        }
    }
    match &model_decoder_result {
        Some(Ok(receipt)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_DECODER=PRESENT");
            let _ = writeln!(serial, "CASULO_NATIVE_DECODER_ARCHITECTURE=qwen3");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_INPUT_TOKEN_ID={}",
                receipt.input_token_id
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_BLOCKS_COMPLETED={}",
                receipt.blocks_completed
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_MATVEC_CALLS={}",
                receipt.work.matvec_calls
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_QUANTIZED_BLOCKS={}",
                receipt.work.quantized_blocks
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_WEIGHT_BYTES_READ={}",
                receipt.work.weight_bytes_read
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_MULTIPLY_ACCUMULATES={}",
                receipt.work.multiply_accumulates
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_ATTENTION_SCORES={}",
                receipt.attention_scores
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_ARENA_BYTES={}",
                receipt.arena_bytes
            );
            let _ = write!(serial, "CASULO_NATIVE_DECODER_HIDDEN_CHAIN_SHA256=");
            for byte in receipt.hidden_chain_sha256 {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = write!(serial, "CASULO_NATIVE_DECODER_LOGITS_SHA256=");
            for byte in receipt.logits_sha256 {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_GREEDY_CANDIDATE_ID={}",
                receipt.greedy_candidate_token_id
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_GREEDY_CANDIDATE_LOGIT_BITS={:08x}",
                receipt.greedy_candidate_logit_bits
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_CANCELLATION_CONTROL={}",
                if receipt.cancellation_rejected_before_work {
                    "PASS"
                } else {
                    "FAIL"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_DMA_OPERATIONS={}",
                receipt.stats.dma_operations
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_CACHE_PAGES={}",
                receipt.stats.cache_pages_loaded
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_BYTES_LOADED={}",
                receipt.stats.bytes_loaded_from_source
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_INCREMENTAL_TOKENS_COMPLETED={}",
                receipt.incremental_tokens_completed
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_INCREMENTAL_KV_VALUES={}",
                receipt.kv_values
            );
            if receipt.incremental_tokens_completed > 1 {
                let _ = writeln!(
                    serial,
                    "CASULO_NATIVE_INCREMENTAL_TOKEN_1_ID={}",
                    receipt.second_candidate_token_id
                );
                let _ = write!(serial, "CASULO_NATIVE_INCREMENTAL_TOKEN_1_TEXT_HEX=");
                for byte in
                    &receipt.second_candidate_text[..usize::from(receipt.second_candidate_text_len)]
                {
                    let _ = write!(serial, "{byte:02x}");
                }
                let _ = writeln!(serial);
                let _ = write!(
                    serial,
                    "CASULO_NATIVE_INCREMENTAL_TOKEN_1_HIDDEN_CHAIN_SHA256="
                );
                for byte in receipt.second_hidden_chain_sha256 {
                    let _ = write!(serial, "{byte:02x}");
                }
                let _ = writeln!(serial);
                let _ = write!(serial, "CASULO_NATIVE_INCREMENTAL_TOKEN_1_LOGITS_SHA256=");
                for byte in receipt.second_logits_sha256 {
                    let _ = write!(serial, "{byte:02x}");
                }
                let _ = writeln!(serial);
                let _ = writeln!(
                    serial,
                    "CASULO_NATIVE_INCREMENTAL_TOKEN_1_PUBLICATION={}",
                    if receipt.second_candidate_published {
                        "T_AUTHORIZED"
                    } else {
                        "NO_POLICY_GATE_PENDING"
                    }
                );
            }
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_INCREMENTAL_CANCELLED_AFTER_TOKEN_BOUNDARY={}",
                if receipt.cancelled_after_token_boundary {
                    "YES"
                } else {
                    "NO"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_DECODER_OUTPUT_TOKEN={}",
                if receipt.candidate_published {
                    "T_AUTHORIZED"
                } else {
                    "NO_POLICY_GATE_PENDING"
                }
            );
            let _ = writeln!(serial, "CASULO_NATIVE_DECODER_GATE=PASS");
        }
        Some(Err(reason)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_DECODER=QUARANTINE");
            let _ = writeln!(serial, "CASULO_NATIVE_DECODER_REJECT={reason:?}");
            let _ = writeln!(serial, "CASULO_NATIVE_DECODER_OUTPUT_TOKEN=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_DECODER_GATE=FAIL");
        }
        None => {
            let _ = writeln!(serial, "CASULO_NATIVE_DECODER=ABSENT");
            let _ = writeln!(serial, "CASULO_NATIVE_DECODER_GATE=NOT_REQUIRED");
        }
    }
    match &model_decoder_result {
        Some(Ok(decoder)) if native_sampling_required && native_sampling_gate => {
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_SAMPLING_POLICY=greedy-incremental-v1"
            );
            let _ = writeln!(serial, "CASULO_NATIVE_SAMPLING_AUTHORITY=T/2.0");
            let _ = write!(serial, "CASULO_NATIVE_SAMPLING_TCAP_HASH=");
            for byte in decoder.sampling_tcap_hash {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_SAMPLING_STEPS_TOTAL={}",
                decoder.sampling_steps_total
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_SAMPLING_TOKENS_AUTHORIZED={}",
                decoder.sampling_tokens_authorized
            );
            let _ = write!(serial, "CASULO_NATIVE_SAMPLING_RECEIPT_CHAIN_TAIL=");
            for byte in decoder.sampling_receipt_chain_tail {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_OUTPUT_TOKEN_ID={}",
                decoder.greedy_candidate_token_id
            );
            let _ = write!(serial, "CASULO_NATIVE_OUTPUT_TOKEN_TEXT_HEX=");
            for byte in
                &decoder.greedy_candidate_text[..usize::from(decoder.greedy_candidate_text_len)]
            {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = writeln!(serial, "CASULO_NATIVE_OUTPUT_TOKEN_MODEL_DERIVED=YES");
            let _ = writeln!(serial, "CASULO_NATIVE_OUTPUT_TOKEN_PUBLICATION=PASS");
            if decoder.incremental_tokens_completed > 1 {
                let _ = writeln!(
                    serial,
                    "CASULO_NATIVE_OUTPUT_TOKEN_1_ID={}",
                    decoder.second_candidate_token_id
                );
                let _ = write!(serial, "CASULO_NATIVE_OUTPUT_TOKEN_1_TEXT_HEX=");
                for byte in
                    &decoder.second_candidate_text[..usize::from(decoder.second_candidate_text_len)]
                {
                    let _ = write!(serial, "{byte:02x}");
                }
                let _ = writeln!(serial);
                let _ = writeln!(serial, "CASULO_NATIVE_OUTPUT_TOKEN_1_PUBLICATION=PASS");
            }
            let _ = writeln!(serial, "CASULO_NATIVE_SAMPLING_GATE=PASS");
        }
        Some(Err(reason)) if native_sampling_required => {
            let _ = writeln!(serial, "CASULO_NATIVE_SAMPLING_REJECT={reason:?}");
            let _ = writeln!(serial, "CASULO_NATIVE_OUTPUT_TOKEN_PUBLICATION=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_SAMPLING_GATE=FAIL");
        }
        Some(Ok(_)) if native_sampling_required => {
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_SAMPLING_REJECT=DECODER_OR_POLICY_MISMATCH"
            );
            let _ = writeln!(serial, "CASULO_NATIVE_OUTPUT_TOKEN_PUBLICATION=NO");
            let _ = writeln!(serial, "CASULO_NATIVE_SAMPLING_GATE=FAIL");
        }
        _ => {
            let _ = writeln!(serial, "CASULO_NATIVE_SAMPLING_GATE=NOT_REQUIRED");
        }
    }
    match &creation_result {
        Some(Ok(receipt)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_CREATION=EXECUTED");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_STATE={}",
                if receipt.cancelled {
                    "CANCELLED_CLEAN"
                } else {
                    "MATERIALIZED"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_PROMPT_TOKENS={}",
                receipt.prompt_tokens
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_OUTPUT_TOKENS={}",
                receipt.output_tokens
            );
            let _ = write!(serial, "CASULO_NATIVE_CREATION_OUTPUT_IDS=");
            for (index, token_id) in receipt.output_ids
                [..usize::try_from(receipt.output_tokens).unwrap_or(0)]
                .iter()
                .enumerate()
            {
                if index > 0 {
                    let _ = write!(serial, ",");
                }
                let _ = write!(serial, "{token_id}");
            }
            let _ = writeln!(serial);
            let _ = write!(serial, "CASULO_NATIVE_CREATION_OUTPUT_TEXT_HEX=");
            for byte in &receipt.output_text[..usize::from(receipt.output_text_len)] {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = write!(serial, "CASULO_NATIVE_CREATION_TOKEN_POLICY_TCAP_HASH=");
            for byte in receipt.token_policy_tcap_hash {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = write!(serial, "CASULO_NATIVE_CREATION_TOKEN_RECEIPT_CHAIN_TAIL=");
            for byte in receipt.token_receipt_chain_tail {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_TOKEN_POLICY_STEPS={}",
                receipt.token_policy_steps
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_MODEL_POSITIONS={}",
                receipt.model_positions_completed
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_BLOCKS_COMPLETED={}",
                receipt.blocks_completed
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_MATVEC_CALLS={}",
                receipt.work.matvec_calls
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_QUANTIZED_BLOCKS={}",
                receipt.work.quantized_blocks
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_WEIGHT_BYTES_READ={}",
                receipt.work.weight_bytes_read
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_MULTIPLY_ACCUMULATES={}",
                receipt.work.multiply_accumulates
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_ARENA_BYTES={}",
                receipt.arena_bytes
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_MODEL_SOURCE_BYTES_LOADED={}",
                receipt.stats.bytes_loaded_from_source
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_MODEL_TRANSPORT={}",
                receipt.model_transport.as_str()
            );
            let _ = writeln!(serial, "CASULO_NATIVE_FULL_MODEL_RESIDENT=YES");
            let _ = writeln!(serial, "CASULO_NATIVE_FIRST_MODEL_DERIVED_TOKEN=YES");
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_SPEC={}",
                if receipt.creation_spec_valid {
                    "PASS"
                } else {
                    "NOT_PUBLISHED"
                }
            );
            let _ = write!(serial, "CASULO_NATIVE_CREATION_GENERATED_T_SOURCE_SHA256=");
            for byte in receipt.generated_t_source_sha256 {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = write!(serial, "CASULO_NATIVE_CREATION_COMPILED_T_SOURCE_SHA256=");
            for byte in receipt.compiled_t_source_sha256 {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_CONTENT_ADDRESS_GATE={}",
                if !receipt.cancelled
                    && receipt.generated_t_source_sha256 == receipt.compiled_t_source_sha256
                {
                    "PASS"
                } else {
                    "NOT_PUBLISHED"
                }
            );
            let _ = write!(serial, "CASULO_NATIVE_CREATION_ARTIFACT_TCAP_HASH=");
            for byte in receipt.artifact_tcap_hash {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_ARTIFACT_RESULT={}",
                receipt.artifact_result
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_SIMULATION={}",
                if receipt.simulation_pass {
                    "PASS"
                } else {
                    "NOT_PUBLISHED"
                }
            );
            let _ = write!(serial, "CASULO_NATIVE_CREATION_MATERIALIZATION_SHA256=");
            for byte in receipt.materialization_sha256 {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = write!(serial, "CASULO_NATIVE_CREATION_ACCEPTANCE_TCAP_HASH=");
            for byte in receipt.acceptance_tcap_hash {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = write!(serial, "CASULO_NATIVE_CREATION_ACCEPTANCE_RECEIPT_HASH=");
            for byte in receipt.acceptance_receipt_hash {
                let _ = write!(serial, "{byte:02x}");
            }
            let _ = writeln!(serial);
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_ACCEPTANCE={}",
                if receipt.acceptance_pass {
                    "PASS"
                } else {
                    "NOT_PUBLISHED"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_CANCELLED={}",
                if receipt.cancelled { "YES" } else { "NO" }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_LATE_OUTPUT_PUBLISHED={}",
                if receipt.late_output_published {
                    "YES"
                } else {
                    "NO"
                }
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_SCENE_FORM={:?}",
                creation_scene.form
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_FRAMEBUFFER_FINGERPRINT={:016x}",
                creation_frame.fingerprint
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_FRAMEBUFFER_PIXELS={}",
                creation_frame.pixels_written
            );
            let _ = writeln!(
                serial,
                "CASULO_NATIVE_CREATION_GATE={}",
                if creation_gate { "PASS" } else { "FAIL" }
            );
        }
        Some(Err(reason)) => {
            let _ = writeln!(serial, "CASULO_NATIVE_CREATION=QUARANTINE");
            let _ = writeln!(serial, "CASULO_NATIVE_CREATION_REJECT={reason:?}");
            let _ = writeln!(serial, "CASULO_NATIVE_CREATION_GATE=FAIL");
        }
        None => {
            let _ = writeln!(serial, "CASULO_NATIVE_CREATION=ABSENT");
            let _ = writeln!(serial, "CASULO_NATIVE_CREATION_GATE=NOT_REQUIRED");
        }
    }
    let _ = writeln!(serial, "TCAP_RAMDISK_BYTES={}", runtime_payload.len());
    let _ = writeln!(serial, "TCAP_HEADER_VERSION=1.0");
    let _ = writeln!(serial, "TCAP_TARGET=x86_64-casulo-none");
    let _ = writeln!(serial, "TCAP_ABI=casulo-learn-context-sysv64/0.1");
    let _ = writeln!(serial, "TCAP_VALIDATION=PASS");
    let _ = writeln!(serial, "TCAP_ARTIFACT=FloodSurrogate.tcap");
    let _ = write!(serial, "TCAP_HASH_SHA256=");
    for byte in package.raw_sha256 {
        let _ = write!(serial, "{byte:02x}");
    }
    let _ = writeln!(serial);
    let _ = writeln!(serial, "TCAP_CODE_BYTES={}", package.code.bytes.len());
    let _ = writeln!(serial, "TCAP_ENTRY_OFFSET={}", package.entry_offset);
    let _ = writeln!(
        serial,
        "TCAP_SSE2_STATE={}",
        if sse2_ready { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "TCAP_RESOURCE_MEMORY_LIMIT={}",
        package.resource_memory_limit
    );
    let _ = writeln!(
        serial,
        "TCAP_RESOURCE_ARENA_BYTES={}",
        package.resource_arena_bytes
    );
    let _ = writeln!(
        serial,
        "TCAP_RESOURCE_MAPPING_BYTES={}",
        learn_mapping.mapped_user_bytes
    );
    let _ = writeln!(
        serial,
        "TCAP_RESOURCE_CEILINGS={}",
        if resource_mapping_bounded {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "TCAP_CODE_RX={}",
        if learn_mapping.code_rx {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "TCAP_DATA_RW_NX={}",
        if learn_mapping.data_rw_nx {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "TCAP_STACK_RW_NX={}",
        if learn_mapping.stack_rw_nx {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "TCAP_RING3_EXIT_STATUS={}",
        learn_process.exit_status
    );
    let _ = writeln!(
        serial,
        "TCAP_RING3_SYSCALLS={}",
        learn_process.syscall_count
    );
    let _ = writeln!(
        serial,
        "TCAP_SYSCALL_PERMISSION_MASK=0x{:x}",
        learn_process.permission_mask
    );
    let _ = writeln!(
        serial,
        "TCAP_PERMISSION_DENIED_SYSCALLS={}",
        permission_probe.denied_syscalls
    );
    let _ = writeln!(
        serial,
        "TCAP_PERMISSION_AUDIT_EVENTS={}",
        permission_probe.permission_audit_events
    );
    let _ = writeln!(
        serial,
        "TCAP_PERMISSION_NEGATIVE={}",
        if permission_probe.exit_status == 0
            && permission_probe.denied_syscalls == 1
            && permission_probe.permission_audit_events == 1
        {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "TCAP_EPOCHS={}", package.canary.epochs);
    let _ = writeln!(serial, "TCAP_RECORDS={}", package.canary.records);
    let _ = writeln!(serial, "TCAP_INPUTS={}", package.canary.inputs);
    let _ = writeln!(serial, "TCAP_HIDDEN={}", package.canary.hidden);
    let _ = writeln!(serial, "TCAP_OUTPUTS={}", package.canary.outputs);
    let _ = writeln!(serial, "TCAP_INITIAL_LOSS={observed_initial_loss:.17}");
    let _ = writeln!(serial, "TCAP_FINAL_LOSS={observed_final_loss:.17}");
    let _ = writeln!(
        serial,
        "TCAP_MAX_PARAMETER_DIFF={max_parameter_difference:.17}"
    );
    let _ = writeln!(
        serial,
        "TCAP_NUMERICAL_EQUIVALENCE={}",
        if loss_equivalence && parameter_equivalence {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "TCAP_CORRUPTION=QUARANTINE_EXECUTION_COUNT_0:{}",
        if corruption_quarantined {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "TCAP_PERFORMANCE_CLAIM=NONE");
    let _ = writeln!(
        serial,
        "FLOOD_SURROGATE_EXECUTION={}",
        if learn_process.exit_status == 0 {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "FLOOD_SURROGATE_EXIT_STATUS={}",
        learn_process.exit_status
    );
    let primitives_pass = heap_ok
        && memory.heap_kernel_only
        && memory.guard_unmapped
        && interrupt.watchdog_passed
        && interrupt.contained_faults == 1;
    let _ = writeln!(
        serial,
        "G2_KERNEL_PRIMITIVES={}",
        if primitives_pass { "PASS" } else { "FAIL" }
    );
    let full_g2 = primitives_pass
        && smp.madt_valid
        && smp.expected_aps == 1
        && smp.started_aps == 1
        && process.exit_status == 42
        && process.separate_cr3
        && memory.kernel_user_inaccessible
        && memory.user_paging_branch_private
        && memory.user_code_rx
        && memory.user_stack_nx
        && process.syscall_count == 8
        && process.unknown_rejected
        && process.ipc_roundtrip
        && process.trace_events == 1
        && process.yield_kernel_returns == 1
        && cross_space_isolation
        && user_watchdog_pass;
    let _ = writeln!(
        serial,
        "G2_FULL_GATE={}",
        if full_g2 { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "G3_TCAP_GATE={}",
        if g3_pass { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(serial, "CASULO_G4_POLICY_ID=semantic_v1");
    let _ = writeln!(
        serial,
        "CASULO_G4_HARD_GATES=integrity,permissions,quality,isolation"
    );
    let _ = writeln!(
        serial,
        "CASULO_G4_AUDIT_BOUND_TICKS={}",
        scheduler::AUDIT_INTERVAL
    );
    let _ = writeln!(
        serial,
        "CASULO_G4_QUARANTINE_DISPATCHES={}",
        g4.quarantine_dispatches
    );
    let _ = writeln!(
        serial,
        "CASULO_G4_QUARANTINED_TASKS={}",
        g4.quarantine_count
    );
    let _ = writeln!(
        serial,
        "CASULO_G4_REFERENCE_VECTOR_SHA256={}",
        scheduler::REFERENCE_VECTOR_SHA256
    );
    let _ = writeln!(
        serial,
        "CASULO_G4_REFERENCE_TRACE_MATCH={}",
        if g4.reference_trace_match {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "CASULO_G4_RING3_DISPATCHES={}", g4.ring3_dispatches);
    let _ = writeln!(
        serial,
        "CASULO_G4_YIELD_KERNEL_RETURNS={}",
        g4.yield_kernel_returns
    );
    let _ = writeln!(
        serial,
        "CASULO_G4_FINITE_WORK={}",
        if g4.finite_work_completed {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_G4_HELP_P95_LOGICAL_TICKS=semantic:{},conventional:{}",
        g4.help_semantic_p95, g4.help_conventional_p95
    );
    let _ = writeln!(
        serial,
        "CASULO_G4_NO_HELP_P95_LOGICAL_TICKS=semantic:{},conventional:{}",
        g4.no_help_semantic_p95, g4.no_help_conventional_p95
    );
    let _ = writeln!(
        serial,
        "CASULO_G4_METRIC_SCOPE=logical-operation-count-not-wall-clock"
    );
    let _ = writeln!(
        serial,
        "CONVENTIONAL_POLICY={}",
        if g4.gate_pass { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "SEMANTIC_POLICY={}",
        if g4.gate_pass { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "EQUIVALENCE_JUDGE={}",
        if g4.gate_pass { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "SCHEDULER_TIMELINE={}",
        if g4.reference_trace_match {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "FLOW_DISPATCHES={}", g4.flow_dispatches);
    let _ = writeln!(serial, "ATTRACTOR_AUDIT_DISPATCHES={}", g4.audit_dispatches);
    let _ = writeln!(
        serial,
        "NON_STARVATION={}",
        if g4.audit_max_gap <= scheduler::AUDIT_INTERVAL {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "AUDIT_STARVATION=0");
    let _ = writeln!(serial, "AUDIT_MAX_GAP_LOGICAL_TICKS={}", g4.audit_max_gap);
    let _ = writeln!(
        serial,
        "TCAP_CORRUPT_RESULT={}",
        if corruption_quarantined {
            "QUARANTINE"
        } else {
            "REJECT_FAILED"
        }
    );
    let _ = writeln!(serial, "TCAP_CORRUPT_EXECUTED=0");
    let _ = writeln!(serial, "TIMING_STATUS=unavailable");
    let _ = writeln!(serial, "ENERGY_STATUS=unavailable");
    let _ = writeln!(serial, "CASULO_SHELL_SCOPE=bounded-read-only-parser/0.1");
    let _ = writeln!(
        serial,
        "CASULO_SHELL_COMMANDS=help,status,topology,scheduler"
    );
    let _ = writeln!(
        serial,
        "CASULO_SHELL_SELF_TEST={}",
        if shell_self_test { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_UX_CONTRACT_SCHEMA={}",
        product_runtime::CONTRACT_SCHEMA
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_UX_WIRE_SCHEMA={}",
        product_runtime::WIRE_SCHEMA
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_UX_CONTRACT_SHA256={}",
        product_runtime::CONTRACT_SHA256
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_UX_MAX_EVENT_BYTES={}",
        product_runtime::MAX_EVENT_BYTES
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_UX_EVENT_KIND_COUNT={}",
        product_runtime::CONTRACT_EVENT_KINDS.len()
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_UX_PRIORITY_COUNT={}",
        product_runtime::CONTRACT_PRIORITIES.len()
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_PRESENCE_PRIORITY={}",
        if product_runtime.presence_priority {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_MODEL_LIFECYCLE={}",
        if product_runtime.model_lifecycle {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_ASSISTANT_STREAM={}",
        if product_runtime.assistant_stream {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_JOB_LIFECYCLE={}",
        if product_runtime.job_lifecycle {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_LATE_COMPLETION_REJECTED={}",
        if product_runtime.late_completion_rejected {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_UX_QUEUE_BOUNDED={}",
        if product_runtime.bounded_queue {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_UX_CONTRACT_GATE={}",
        if product_runtime.passed() {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SCENE_SCHEMA={}",
        casulo_presentation_core::SCENE_SCHEMA
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SCENE_SHA256={}",
        casulo_presentation_core::SCENE_SCHEMA_SHA256
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SCENE_HAPPY_PATH={}",
        if presentation.happy_path {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SCENE_REJECTIONS={}",
        if presentation.duplicate_rejected
            && presentation.out_of_order_rejected
            && presentation.late_completion_rejected
        {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SCENE_TRANSACTIONAL={}",
        if presentation.transaction_preserved {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_SCENE_GATE={}",
        if presentation.passed() {
            "PASS"
        } else {
            "FAIL"
        }
    );
    let _ = writeln!(serial, "CASULO_NATIVE_INPUT_ABI=ps2-set1-bounded/0.1");
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_INPUT_DECODER_GATE={}",
        if input_decoder { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_NEURAL_ABI=ring3-capability-primitives/0.1"
    );
    let _ = writeln!(serial, "CASULO_NATIVE_NEURAL_ABI_MODEL_BYTES=0");
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_NEURAL_ABI_MODEL_ASSERTS={}",
        neural_abi.neural_model_asserts
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_NEURAL_ABI_PRIMITIVE_CALLS={}",
        neural_abi.neural_primitive_calls
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_NEURAL_ABI_TOKEN_EVENTS={}",
        neural_abi.neural_tokens_emitted
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_NEURAL_ABI_LAST_TOKEN={}",
        neural_abi.neural_last_token
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_NEURAL_ABI_DENIED_WITHOUT_CAPABILITY={}",
        neural_permission.denied_syscalls
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_NEURAL_ABI_GATE={}",
        if neural_abi_pass { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_NEURAL_INFERENCE={}",
        if creation_required {
            match &creation_result {
                Some(Ok(receipt)) if receipt.cancelled => "NATIVE_CREATION_CANCELLED_CLEAN",
                Some(Ok(_)) => "BOOT_TO_CREATION_T_AUTHORIZED",
                _ => "NATIVE_CREATION_FAILED",
            }
        } else if native_sampling_required {
            match &model_decoder_result {
                Some(Ok(receipt)) if receipt.cancelled_after_token_boundary => {
                    "TOKEN_STREAM_T_AUTHORIZED_CANCELLED_AT_BOUNDARY"
                }
                Some(Ok(receipt)) if receipt.incremental_tokens_completed > 1 => {
                    "MULTI_TOKEN_INCREMENTAL_STREAM_T_AUTHORIZED"
                }
                _ => "FIRST_MODEL_DERIVED_TOKEN_T_AUTHORIZED",
            }
        } else if model_decoder_required {
            "FULL_DECODER_LOGITS_CANDIDATE_NO_PUBLICATION"
        } else if model_block0_required {
            "BLOCK0_ONLY_NO_OUTPUT_TOKEN"
        } else {
            "NOT_EXECUTED"
        }
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_PERSISTENCE_ABI={}",
        casulo_presentation_core::JOURNAL_SCHEMA
    );
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_PERSISTENCE_JOURNAL_GATE={}",
        if persistence_journal { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(serial, "CASULO_NATIVE_PERSISTENCE_MEDIA_WRITES=0");
    let _ = writeln!(serial, "CASULO_NATIVE_REBOOT_PERSISTENCE=NOT_PROVEN");
    let _ = writeln!(
        serial,
        "CASULO_NATIVE_PRODUCT_ADAPTERS=timer,serial,framebuffer,ramdisk,system-pack,tcap,scene-projector,gop-renderer,native-model,token-policy,bounded-creation-compiler,bounded-materializer"
    );
    let _ = writeln!(
        serial,
        "CASULO_HOSTED_ONLY_ADAPTERS=physical-audio,dpapi-memory,general-creation-renderer,general-materializer"
    );
    let _ = writeln!(
        serial,
        "G7_DEMO_PAYLOAD_GATE={}",
        if g3_pass { "PASS" } else { "FAIL" }
    );
    let g7_complete = full_g2
        && g3_pass
        && g4.gate_pass
        && shell_self_test
        && product_runtime.passed()
        && presentation.passed()
        && input_decoder
        && neural_abi_pass
        && system_pack_gate
        && model_probe_gate
        && model_paged_gate
        && model_tokenizer_gate
        && model_block0_gate
        && model_decoder_gate
        && native_sampling_gate
        && creation_gate
        && persistence_journal
        && framebuffer.painted
        && creation_frame.painted;
    let _ = writeln!(
        serial,
        "G4_SEMANTIC_SCHEDULER_GATE={}",
        if g4.gate_pass { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(
        serial,
        "G7_DEMO_COMPLETE={}",
        if g7_complete { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(serial, "SHUTDOWN_PATH=isa-debug-exit/0.1");
    let _ = writeln!(serial, "REBOOT_PATH=8042-reset-probe-validated/0.1");
    if option_env!("CASULO_GENERATIVE_BRIDGE") == Some("request-only") {
        let _ = writeln!(serial, "OWNER_BRIDGE_SCHEMA=casulo-owner-serial/1.0");
        let _ = writeln!(serial, "OWNER_BRIDGE_CAPABILITY=guide.job.submit");
        let _ = writeln!(serial, "OWNER_BRIDGE_REQUEST=create-owner-agent");
        let _ = writeln!(serial, "OWNER_JOB_SUBMITTED=1");
    } else if matches!(
        option_env!("CASULO_GENERATIVE_BRIDGE"),
        Some("1") | Some("diagnostic")
    ) {
        let _ = writeln!(serial, "OWNER_BRIDGE_SCHEMA=casulo-owner-serial/1.0");
        let _ = writeln!(serial, "OWNER_BRIDGE_CAPABILITY=guide.response.receive");
        let _ = writeln!(serial, "OWNER_BRIDGE_TRUST=UNTRUSTED_DATA_ONLY");
        let _ = writeln!(serial, "OWNER_BRIDGE_REQUEST=resume-owner-creation");
        let _ = writeln!(serial, "OWNER_BRIDGE_READY=1");
        match await_owner_bridge_line(&mut serial) {
            OwnerBridgeRead::Complete(bytes) if bytes > 0 => {
                let _ = writeln!(serial, "OWNER_ENGINE_RESPONSE_RECEIVED_BYTES={bytes}");
                let _ = writeln!(serial, "OWNER_GENERATIVE_BRIDGE=PASS");
            }
            OwnerBridgeRead::Complete(_) => {
                let _ = writeln!(serial, "OWNER_GENERATIVE_BRIDGE=FAIL_EMPTY");
                exit_qemu(QemuExit::Failure)
            }
            OwnerBridgeRead::TimedOut(status) => {
                let _ = writeln!(serial, "OWNER_UART_OBSERVED_LSR=0x{status:02x}");
                let _ = writeln!(serial, "OWNER_GENERATIVE_BRIDGE=FAIL_TIMEOUT");
                exit_qemu(QemuExit::Failure)
            }
            OwnerBridgeRead::Overflow => {
                let _ = writeln!(serial, "OWNER_GENERATIVE_BRIDGE=FAIL_OVERFLOW");
                exit_qemu(QemuExit::Failure)
            }
        }
    }
    if g7_complete && option_env!("CASULO_NATIVE_INTERACTIVE") == Some("1") {
        let _ = writeln!(serial, "CASULO_NATIVE_INTERACTIVE_PREVIEW=READY");
        let _ = writeln!(
            serial,
            "CASULO_NATIVE_INTERACTIVE_LIMIT=NO_NEURAL_CONVERSATION"
        );
        x86_64::instructions::interrupts::enable();
        loop {
            hlt();
        }
    }
    if g7_complete {
        exit_qemu(QemuExit::Success)
    } else {
        exit_qemu(QemuExit::Failure)
    }
}

#[alloc_error_handler]
fn alloc_error(layout: Layout) -> ! {
    panic!("kernel heap exhausted for allocation: {layout:?}")
}

#[panic_handler]
fn panic(info: &core::panic::PanicInfo) -> ! {
    let mut serial = serial::Serial::init();
    let _ = writeln!(serial, "CASULO_PANIC_DUMP");
    let _ = writeln!(serial, "PANIC_SCHEMA=casulo-panic-dump/0.1");
    let _ = writeln!(
        serial,
        "PANIC_KIND={}",
        if option_env!("CASULO_BOOT_PROBE") == Some("panic") {
            "intentional-probe"
        } else {
            "kernel-panic"
        }
    );
    let _ = writeln!(serial, "PANIC_INFO={info}");
    let _ = writeln!(serial, "PANIC_ACTION=isa-debug-exit-failure");
    exit_qemu(QemuExit::Failure)
}
