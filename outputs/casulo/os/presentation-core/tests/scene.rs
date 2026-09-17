use casulo_presentation_core::{
    EventKind, InputError, InputUpdate, JobState, Journal, JournalError, KeyboardLine, ModelState,
    PixelOrder, ProjectionError, ProjectionEvent, SceneForm, SceneState, Surface, render_scene,
    self_test,
};

#[test]
fn scene_transaction_stack_budget_remains_bounded() {
    // SceneState::apply keeps one complete candidate beside the live state.
    // Four states cover caller + candidate + self-test comparison temporaries.
    let worst_case = core::mem::size_of::<SceneState>() * 4;
    assert!(
        worst_case <= 64 * 1024,
        "scene stack budget grew to {worst_case} bytes"
    );
}

#[test]
fn scan_code_input_is_bounded_and_deterministic() {
    let mut line = KeyboardLine::<6>::new();
    for code in [0x2e, 0x1e, 0x1f, 0x16, 0x26, 0x18] {
        assert_eq!(line.feed_set1(code), Ok(InputUpdate::Changed));
    }
    assert_eq!(line.as_bytes(), b"casulo");
    assert_eq!(line.feed_set1(0x20), Err(InputError::CapacityExceeded));
    assert_eq!(line.as_bytes(), b"casulo");
    assert_eq!(line.feed_set1(0x1c), Ok(InputUpdate::Submitted));

    let mut shifted = KeyboardLine::<2>::new();
    assert_eq!(shifted.feed_set1(0x2a), Ok(InputUpdate::Ignored));
    assert_eq!(shifted.feed_set1(0x14), Ok(InputUpdate::Changed));
    assert_eq!(shifted.feed_set1(0xaa), Ok(InputUpdate::Ignored));
    assert_eq!(shifted.as_bytes(), b"T");
}

#[test]
fn persistence_journal_is_chained_bounded_and_content_free() {
    let mut journal = Journal::new();
    let first = journal.append(1, b"segredo-nao-persistido").unwrap();
    let second = journal.append(2, b"decisao").unwrap();
    assert_ne!(first.payload_sha256, [0; 32]);
    assert_eq!(second.previous_sha256, first.record_sha256);
    assert_eq!(journal.validate(), Ok(()));
    assert_eq!(journal.records().count(), 2);
    assert_eq!(journal.append(3, b""), Err(JournalError::EmptyPayload));
}
use serde_json::Value;
use std::{fs, path::PathBuf};

fn fixture() -> Value {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("schemas/product/stark-jobs-conformance-v1.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn kind(value: &str) -> EventKind {
    match value {
        "PRESENCE_READY" => EventKind::PresenceReady,
        "MODEL_LOADING" => EventKind::ModelLoading,
        "MODEL_READY" => EventKind::ModelReady,
        "INPUT_REQUEST" => EventKind::InputRequest,
        "ASSISTANT_START" => EventKind::AssistantStart,
        "ASSISTANT_TOKEN" => EventKind::AssistantToken,
        "ASSISTANT_END" => EventKind::AssistantEnd,
        "JOB_STARTED" => EventKind::JobStarted,
        "JOB_MILESTONE" => EventKind::JobMilestone,
        "JOB_COMPLETED" => EventKind::JobCompleted,
        "JOB_FAILED" => EventKind::JobFailed,
        "JOB_CANCELLED" => EventKind::JobCancelled,
        "NOTICE" => EventKind::Notice,
        "RECOVERABLE_ERROR" => EventKind::RecoverableError,
        other => panic!("unknown fixture kind {other}"),
    }
}

fn digest(value: &str) -> [u8; 32] {
    let mut result = [0; 32];
    for (index, slot) in result.iter_mut().enumerate() {
        *slot = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16).unwrap();
    }
    result
}

#[test]
fn bounded_self_test_passes() {
    assert!(self_test().passed());
}

#[test]
fn shared_hosted_native_fixture_matches_expected_projection() {
    let fixture = fixture();
    assert_eq!(fixture["runtime_evidence"], false);
    let mut scene = SceneState::new();
    for raw in fixture["accepted"].as_array().unwrap() {
        let payload = raw["payload"].as_object().unwrap();
        let event_kind = kind(raw["kind"].as_str().unwrap());
        let subject = payload
            .get("turn_id")
            .or_else(|| payload.get("job_id"))
            .and_then(Value::as_str)
            .unwrap_or("0")
            .parse::<u32>()
            .unwrap();
        let sequence = payload.get("sequence").and_then(Value::as_u64).unwrap_or(0) as u16;
        let text = payload
            .get("text")
            .or_else(|| payload.get("prompt"))
            .or_else(|| payload.get("summary"))
            .and_then(Value::as_str)
            .unwrap_or("");
        let evidence = payload
            .get("evidence_sha256")
            .and_then(Value::as_str)
            .map(digest)
            .unwrap_or([0; 32]);
        scene
            .apply(ProjectionEvent {
                event_id: raw["event_id"].as_str().unwrap().parse().unwrap(),
                subject_id: subject,
                kind: event_kind,
                sequence,
                text: text.as_bytes(),
                evidence_sha256: evidence,
            })
            .unwrap();
    }
    let expected = &fixture["expected"];
    assert_eq!(scene.presence, expected["presence"].as_bool().unwrap());
    assert_eq!(scene.model, ModelState::Ready);
    assert_eq!(scene.form, SceneForm::Materialized);
    assert_eq!(scene.notice.as_str(), expected["notice"].as_str().unwrap());
    assert_eq!(scene.active_turn, None);
    assert_eq!(
        u64::from(scene.next_token_sequence),
        expected["next_token_sequence"].as_u64().unwrap()
    );
    assert_eq!(
        scene.message.text.as_str(),
        expected["message_text"].as_str().unwrap()
    );
    assert!(scene.message.complete);
    let job = scene.jobs[0].unwrap();
    assert_eq!(job.state, JobState::Completed);
    assert_eq!(
        job.summary.as_str(),
        expected["job_summary"].as_str().unwrap()
    );
    assert_eq!(
        u64::from(job.milestone_count),
        expected["milestone_count"].as_u64().unwrap()
    );
    assert_eq!(
        u64::from(scene.receipt_count),
        expected["receipt_count"].as_u64().unwrap()
    );
}

#[test]
fn full_projection_matches_hosted_semantics() {
    let evidence = [0xaa; 32];
    let mut scene = SceneState::new();
    let tape = [
        ProjectionEvent::control(1, 0, EventKind::PresenceReady, 0, b"Estou aqui."),
        ProjectionEvent::control(2, 0, EventKind::ModelLoading, 0, b""),
        ProjectionEvent::control(3, 0, EventKind::ModelReady, 0, b""),
        ProjectionEvent::control(4, 7, EventKind::AssistantStart, 0, b""),
        ProjectionEvent::control(5, 7, EventKind::AssistantToken, 1, b"Entendi "),
        ProjectionEvent::control(6, 7, EventKind::AssistantToken, 2, b"a ideia."),
        ProjectionEvent::control(7, 7, EventKind::AssistantEnd, 0, b""),
        ProjectionEvent::job(
            8,
            11,
            EventKind::JobStarted,
            1,
            b"Ideia preservada.",
            evidence,
        ),
        ProjectionEvent::job(
            9,
            11,
            EventKind::JobMilestone,
            2,
            b"Forma emergindo.",
            evidence,
        ),
        ProjectionEvent::job(
            10,
            11,
            EventKind::JobCompleted,
            3,
            b"Criacao pronta.",
            evidence,
        ),
    ];
    for event in tape {
        scene.apply(event).unwrap();
    }
    assert!(scene.presence);
    assert_eq!(scene.model, ModelState::Ready);
    assert_eq!(scene.form, SceneForm::Materialized);
    assert_eq!(scene.active_turn, None);
    assert_eq!(scene.next_token_sequence, 3);
    assert_eq!(scene.message.text.as_str(), "Entendi a ideia.");
    assert!(scene.message.complete);
    let job = scene.jobs[0].unwrap();
    assert_eq!(job.state, JobState::Completed);
    assert_eq!(job.milestone_count, 1);
    assert_eq!(job.summary.as_str(), "Criacao pronta.");
    assert_eq!(scene.receipt_count, 3);
}

#[test]
fn every_rejection_is_transactional() {
    let evidence = [0x55; 32];
    let mut scene = SceneState::new();
    scene
        .apply(ProjectionEvent::control(
            1,
            9,
            EventKind::AssistantStart,
            0,
            b"",
        ))
        .unwrap();
    let stable = scene;
    assert_eq!(
        scene.apply(ProjectionEvent::control(
            2,
            9,
            EventKind::AssistantToken,
            2,
            b"fora",
        )),
        Err(ProjectionError::TokenOutOfOrder)
    );
    assert_eq!(scene, stable);

    let mut job = SceneState::new();
    let stable = job;
    assert_eq!(
        job.apply(ProjectionEvent::job(
            10,
            3,
            EventKind::JobStarted,
            1,
            b"sem evidencia",
            [0; 32],
        )),
        Err(ProjectionError::MissingEvidence)
    );
    assert_eq!(job, stable);

    job.apply(ProjectionEvent::job(
        11,
        3,
        EventKind::JobStarted,
        1,
        b"ativo",
        evidence,
    ))
    .unwrap();
    job.apply(ProjectionEvent::job(
        12,
        3,
        EventKind::JobCancelled,
        2,
        b"cancelado",
        evidence,
    ))
    .unwrap();
    let stable = job;
    assert_eq!(
        job.apply(ProjectionEvent::job(
            13,
            3,
            EventKind::JobCompleted,
            3,
            b"tardio",
            evidence,
        )),
        Err(ProjectionError::JobTerminal)
    );
    assert_eq!(job, stable);
}

#[test]
fn utf8_and_capacity_are_fail_closed() {
    let mut scene = SceneState::new();
    let stable = scene;
    assert_eq!(
        scene.apply(ProjectionEvent::control(
            1,
            0,
            EventKind::PresenceReady,
            0,
            &[0xff],
        )),
        Err(ProjectionError::InvalidUtf8)
    );
    assert_eq!(scene, stable);

    let oversized = [b'x'; 513];
    assert_eq!(
        scene.apply(ProjectionEvent::control(
            2,
            0,
            EventKind::PresenceReady,
            0,
            &oversized,
        )),
        Err(ProjectionError::TextTooLong)
    );
    assert_eq!(scene, stable);
}

#[test]
fn renderer_is_stable_and_receipt_driven() {
    const WIDTH: usize = 320;
    const HEIGHT: usize = 240;
    let mut first = vec![0_u8; WIDTH * HEIGHT * 4];
    let mut second = vec![0_u8; WIDTH * HEIGHT * 4];
    let scene = SceneState::new();
    let first_receipt = render_scene(
        &mut Surface::new(&mut first, WIDTH, HEIGHT, WIDTH, 4, PixelOrder::Bgr).unwrap(),
        &scene,
    );
    let second_receipt = render_scene(
        &mut Surface::new(&mut second, WIDTH, HEIGHT, WIDTH, 4, PixelOrder::Bgr).unwrap(),
        &scene,
    );
    assert_eq!(first, second);
    assert_eq!(first_receipt, second_receipt);
    assert_eq!(first_receipt.receipt_nodes, 0);

    let evidence = [0xab; 32];
    let mut evolved = scene;
    evolved
        .apply(ProjectionEvent::job(
            1,
            1,
            EventKind::JobStarted,
            1,
            b"Ideia preservada.",
            evidence,
        ))
        .unwrap();
    let mut evolved_frame = vec![0_u8; WIDTH * HEIGHT * 4];
    let evolved_receipt = render_scene(
        &mut Surface::new(&mut evolved_frame, WIDTH, HEIGHT, WIDTH, 4, PixelOrder::Bgr).unwrap(),
        &evolved,
    );
    assert_ne!(
        first_receipt.framebuffer_fingerprint,
        evolved_receipt.framebuffer_fingerprint
    );
    assert_eq!(evolved_receipt.receipt_nodes, 1);
}
