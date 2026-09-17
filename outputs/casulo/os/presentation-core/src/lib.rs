#![no_std]

//! Bounded, authority-free presentation state for Hosted/Native convergence.
//!
//! This crate is deliberately independent from framebuffer, model and storage
//! drivers. It accepts only events that have already crossed the product
//! contract validator and projects them into a fixed-capacity scene. It cannot
//! create capabilities, receipts, completion or progress.

use core::str;

mod input;
mod journal;
mod renderer;
pub use input::{InputError, InputUpdate, KeyboardLine, self_test as input_self_test};
pub use journal::{
    JOURNAL_SCHEMA, Journal, JournalError, JournalRecord, self_test as journal_self_test,
};
pub use renderer::{Color, PixelOrder, RenderError, RenderReceipt, Surface, render_scene};

pub const WIRE_SCHEMA: &str = "casulo.owner-ux-event/1.0";
pub const CONTRACT_SHA256: &str =
    "4d209cce708d843ffef50ac606ba199151be39eb9ecfff9c2c9fae233d24bcb9";
pub const SCENE_SCHEMA: &str = "casulo.stark-jobs-scene/1.0";
pub const SCENE_SCHEMA_SHA256: &str =
    "804ceb12b510f250cfd41a6e49185fe8db73f13c09a7f3288703368889435a8d";

pub const MAX_SEEN_EVENTS: usize = 64;
pub const MAX_JOBS: usize = 4;
pub const MAX_MESSAGE_BYTES: usize = 8 * 1024;
pub const MAX_NOTICE_BYTES: usize = 512;
pub const MAX_ERROR_BYTES: usize = 512;
pub const MAX_JOB_SUMMARY_BYTES: usize = 512;

const DEFAULT_NOTICE: &[u8] = b"Abrindo um espaco silencioso para criar.";
const DEFAULT_PRESENCE: &[u8] = b"Estou aqui.";
const DEFAULT_INPUT: &[u8] = b"Conte do seu jeito.";
const DEFAULT_NOTICE_EVENT: &[u8] = b"Aviso do Casulo.";
const DEFAULT_ERROR: &[u8] = b"Algo parou, mas o que ja existe foi preservado.";
const MODEL_LOADING_NOTICE: &[u8] = b"A inteligencia local esta despertando. Voce ja pode comecar.";
const MODEL_READY_NOTICE: &[u8] = b"Presenca local pronta.";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EventKind {
    PresenceReady,
    ModelLoading,
    ModelReady,
    InputRequest,
    AssistantStart,
    AssistantToken,
    AssistantEnd,
    JobStarted,
    JobMilestone,
    JobCompleted,
    JobFailed,
    JobCancelled,
    Notice,
    RecoverableError,
}

impl EventKind {
    pub const fn is_job(self) -> bool {
        matches!(
            self,
            Self::JobStarted
                | Self::JobMilestone
                | Self::JobCompleted
                | Self::JobFailed
                | Self::JobCancelled
        )
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SceneForm {
    Silence,
    Presence,
    Listening,
    Thinking,
    Conversation,
    FirstForm,
    Formation,
    Materialized,
    Cancelled,
    RecoverableFailure,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModelState {
    Absent,
    Loading,
    Ready,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum JobState {
    Active,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProjectionError {
    DuplicateEvent,
    CapacityExceeded,
    InvalidUtf8,
    TextTooLong,
    InvalidModelTransition,
    StreamAlreadyActive,
    StreamNotActive,
    TokenOutOfOrder,
    MissingToken,
    MissingEvidence,
    MissingSummary,
    JobAlreadyExists,
    JobNotStarted,
    JobTerminal,
    JobSequence,
}

#[derive(Clone, Copy, Eq, PartialEq)]
pub struct FixedText<const N: usize> {
    bytes: [u8; N],
    len: u16,
}

impl<const N: usize> FixedText<N> {
    pub const fn new() -> Self {
        Self {
            bytes: [0; N],
            len: 0,
        }
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes[..usize::from(self.len)]
    }

    pub fn as_str(&self) -> &str {
        // All writes validate UTF-8 before mutating the buffer.
        unsafe { str::from_utf8_unchecked(self.as_bytes()) }
    }

    pub const fn len(&self) -> usize {
        self.len as usize
    }

    pub const fn is_empty(&self) -> bool {
        self.len == 0
    }

    fn replace(&mut self, value: &[u8]) -> Result<(), ProjectionError> {
        str::from_utf8(value).map_err(|_| ProjectionError::InvalidUtf8)?;
        if value.len() > N || value.len() > usize::from(u16::MAX) {
            return Err(ProjectionError::TextTooLong);
        }
        let previous_len = usize::from(self.len);
        self.bytes[..value.len()].copy_from_slice(value);
        if previous_len > value.len() {
            self.bytes[value.len()..previous_len].fill(0);
        }
        self.len = value.len() as u16;
        Ok(())
    }

    fn append(&mut self, value: &[u8]) -> Result<(), ProjectionError> {
        str::from_utf8(value).map_err(|_| ProjectionError::InvalidUtf8)?;
        let start = usize::from(self.len);
        let end = start
            .checked_add(value.len())
            .ok_or(ProjectionError::TextTooLong)?;
        if end > N || end > usize::from(u16::MAX) {
            return Err(ProjectionError::TextTooLong);
        }
        self.bytes[start..end].copy_from_slice(value);
        self.len = end as u16;
        Ok(())
    }
}

impl<const N: usize> Default for FixedText<N> {
    fn default() -> Self {
        Self::new()
    }
}

impl<const N: usize> core::fmt::Debug for FixedText<N> {
    fn fmt(&self, formatter: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        formatter
            .debug_tuple("FixedText")
            .field(&self.as_str())
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProjectionEvent<'a> {
    pub event_id: u32,
    pub subject_id: u32,
    pub kind: EventKind,
    pub sequence: u16,
    pub text: &'a [u8],
    pub evidence_sha256: [u8; 32],
}

impl<'a> ProjectionEvent<'a> {
    pub const fn control(
        event_id: u32,
        subject_id: u32,
        kind: EventKind,
        sequence: u16,
        text: &'a [u8],
    ) -> Self {
        Self {
            event_id,
            subject_id,
            kind,
            sequence,
            text,
            evidence_sha256: [0; 32],
        }
    }

    pub const fn job(
        event_id: u32,
        job_id: u32,
        kind: EventKind,
        sequence: u16,
        summary: &'a [u8],
        evidence_sha256: [u8; 32],
    ) -> Self {
        Self {
            event_id,
            subject_id: job_id,
            kind,
            sequence,
            text: summary,
            evidence_sha256,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MessageView {
    pub turn_id: u32,
    pub text: FixedText<MAX_MESSAGE_BYTES>,
    pub complete: bool,
    pub present: bool,
}

impl MessageView {
    pub const fn empty() -> Self {
        Self {
            turn_id: 0,
            text: FixedText::new(),
            complete: false,
            present: false,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct JobView {
    pub job_id: u32,
    pub state: JobState,
    pub last_sequence: u16,
    pub milestone_count: u16,
    pub summary: FixedText<MAX_JOB_SUMMARY_BYTES>,
    pub evidence_sha256: [u8; 32],
}

impl JobView {
    const fn empty() -> Option<Self> {
        None
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SceneState {
    pub presence: bool,
    pub model: ModelState,
    pub form: SceneForm,
    pub notice: FixedText<MAX_NOTICE_BYTES>,
    pub active_turn: Option<u32>,
    pub next_token_sequence: u16,
    pub message: MessageView,
    pub jobs: [Option<JobView>; MAX_JOBS],
    pub receipt_count: u16,
    pub recoverable_error: FixedText<MAX_ERROR_BYTES>,
    seen_event_ids: [u32; MAX_SEEN_EVENTS],
    seen_len: u8,
}

impl SceneState {
    pub fn new() -> Self {
        let mut state = Self {
            presence: false,
            model: ModelState::Absent,
            form: SceneForm::Silence,
            notice: FixedText::new(),
            active_turn: None,
            next_token_sequence: 1,
            message: MessageView::empty(),
            jobs: [JobView::empty(); MAX_JOBS],
            receipt_count: 0,
            recoverable_error: FixedText::new(),
            seen_event_ids: [0; MAX_SEEN_EVENTS],
            seen_len: 0,
        };
        state
            .notice
            .replace(DEFAULT_NOTICE)
            .expect("default notice fits fixed buffer");
        state
    }

    pub const fn seen_events(&self) -> usize {
        self.seen_len as usize
    }

    pub fn apply(&mut self, event: ProjectionEvent<'_>) -> Result<(), ProjectionError> {
        if self.seen_event_ids[..self.seen_events()].contains(&event.event_id) {
            return Err(ProjectionError::DuplicateEvent);
        }
        if self.seen_events() == MAX_SEEN_EVENTS {
            return Err(ProjectionError::CapacityExceeded);
        }
        if event.kind.is_job() && !event.evidence_sha256.iter().any(|byte| *byte != 0) {
            return Err(ProjectionError::MissingEvidence);
        }
        // Fixed-size copy gives transaction semantics: any rejection leaves the
        // last accepted scene fully intact.
        let mut candidate = *self;
        candidate.apply_kind(event)?;
        candidate.seen_event_ids[candidate.seen_events()] = event.event_id;
        candidate.seen_len += 1;
        *self = candidate;
        Ok(())
    }

    fn apply_kind(&mut self, event: ProjectionEvent<'_>) -> Result<(), ProjectionError> {
        match event.kind {
            EventKind::PresenceReady => {
                self.presence = true;
                self.form = SceneForm::Presence;
                self.notice.replace(if event.text.is_empty() {
                    DEFAULT_PRESENCE
                } else {
                    event.text
                })?;
            }
            EventKind::ModelLoading => {
                if self.model != ModelState::Absent {
                    return Err(ProjectionError::InvalidModelTransition);
                }
                self.model = ModelState::Loading;
                self.notice.replace(MODEL_LOADING_NOTICE)?;
            }
            EventKind::ModelReady => {
                if self.model != ModelState::Loading {
                    return Err(ProjectionError::InvalidModelTransition);
                }
                self.model = ModelState::Ready;
                self.notice.replace(MODEL_READY_NOTICE)?;
            }
            EventKind::InputRequest => {
                self.form = SceneForm::Listening;
                self.notice.replace(if event.text.is_empty() {
                    DEFAULT_INPUT
                } else {
                    event.text
                })?;
            }
            EventKind::AssistantStart => {
                if self.active_turn.is_some() {
                    return Err(ProjectionError::StreamAlreadyActive);
                }
                self.active_turn = Some(event.subject_id);
                self.next_token_sequence = 1;
                self.form = SceneForm::Thinking;
                self.message = MessageView {
                    turn_id: event.subject_id,
                    text: FixedText::new(),
                    complete: false,
                    present: true,
                };
            }
            EventKind::AssistantToken => {
                if event.text.is_empty() {
                    return Err(ProjectionError::MissingToken);
                }
                if self.active_turn != Some(event.subject_id) {
                    return Err(ProjectionError::StreamNotActive);
                }
                if event.sequence != self.next_token_sequence {
                    return Err(ProjectionError::TokenOutOfOrder);
                }
                self.message.text.append(event.text)?;
                self.next_token_sequence = self.next_token_sequence.saturating_add(1);
                self.form = SceneForm::Conversation;
            }
            EventKind::AssistantEnd => {
                if self.active_turn != Some(event.subject_id) {
                    return Err(ProjectionError::StreamNotActive);
                }
                self.message.complete = true;
                self.active_turn = None;
                self.form = SceneForm::Presence;
            }
            EventKind::JobStarted => self.start_job(event)?,
            EventKind::JobMilestone
            | EventKind::JobCompleted
            | EventKind::JobFailed
            | EventKind::JobCancelled => self.advance_job(event)?,
            EventKind::Notice => {
                self.notice.replace(if event.text.is_empty() {
                    DEFAULT_NOTICE_EVENT
                } else {
                    event.text
                })?;
            }
            EventKind::RecoverableError => {
                let text = if event.text.is_empty() {
                    DEFAULT_ERROR
                } else {
                    event.text
                };
                self.recoverable_error.replace(text)?;
                self.notice.replace(text)?;
                self.form = SceneForm::RecoverableFailure;
            }
        }
        Ok(())
    }

    fn start_job(&mut self, event: ProjectionEvent<'_>) -> Result<(), ProjectionError> {
        if event.text.is_empty() {
            return Err(ProjectionError::MissingSummary);
        }
        if event.sequence != 1 {
            return Err(ProjectionError::JobSequence);
        }
        if self
            .jobs
            .iter()
            .flatten()
            .any(|job| job.job_id == event.subject_id)
        {
            return Err(ProjectionError::JobAlreadyExists);
        }
        let slot = self
            .jobs
            .iter_mut()
            .find(|slot| slot.is_none())
            .ok_or(ProjectionError::CapacityExceeded)?;
        let mut summary = FixedText::new();
        summary.replace(event.text)?;
        *slot = Some(JobView {
            job_id: event.subject_id,
            state: JobState::Active,
            last_sequence: 1,
            milestone_count: 0,
            summary,
            evidence_sha256: event.evidence_sha256,
        });
        self.receipt_count = self.receipt_count.saturating_add(1);
        self.form = SceneForm::FirstForm;
        self.notice.replace(event.text)?;
        Ok(())
    }

    fn advance_job(&mut self, event: ProjectionEvent<'_>) -> Result<(), ProjectionError> {
        if event.text.is_empty() {
            return Err(ProjectionError::MissingSummary);
        }
        let job = self
            .jobs
            .iter_mut()
            .flatten()
            .find(|job| job.job_id == event.subject_id)
            .ok_or(ProjectionError::JobNotStarted)?;
        if job.state != JobState::Active {
            return Err(ProjectionError::JobTerminal);
        }
        if event.sequence != job.last_sequence.saturating_add(1) {
            return Err(ProjectionError::JobSequence);
        }
        job.summary.replace(event.text)?;
        job.evidence_sha256 = event.evidence_sha256;
        job.last_sequence = event.sequence;
        job.state = match event.kind {
            EventKind::JobMilestone => {
                job.milestone_count = job.milestone_count.saturating_add(1);
                JobState::Active
            }
            EventKind::JobCompleted => JobState::Completed,
            EventKind::JobFailed => JobState::Failed,
            EventKind::JobCancelled => JobState::Cancelled,
            _ => return Err(ProjectionError::JobSequence),
        };
        self.receipt_count = self.receipt_count.saturating_add(1);
        self.form = match event.kind {
            EventKind::JobMilestone => SceneForm::Formation,
            EventKind::JobCompleted => SceneForm::Materialized,
            EventKind::JobFailed => SceneForm::RecoverableFailure,
            EventKind::JobCancelled => SceneForm::Cancelled,
            _ => return Err(ProjectionError::JobSequence),
        };
        if event.kind == EventKind::JobFailed {
            self.recoverable_error.replace(event.text)?;
        }
        self.notice.replace(event.text)?;
        Ok(())
    }
}

impl Default for SceneState {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SelfTestSummary {
    pub happy_path: bool,
    pub duplicate_rejected: bool,
    pub out_of_order_rejected: bool,
    pub late_completion_rejected: bool,
    pub transaction_preserved: bool,
}

impl SelfTestSummary {
    pub const fn passed(self) -> bool {
        self.happy_path
            && self.duplicate_rejected
            && self.out_of_order_rejected
            && self.late_completion_rejected
            && self.transaction_preserved
    }
}

// Keep the sizeable transactional copies in this bounded frame.  Inlining the
// self-test into the kernel entry point previously made the release optimizer
// combine it with unrelated boot frames and exhausted the 128 KiB boot stack.
#[inline(never)]
pub fn self_test() -> SelfTestSummary {
    let evidence = [0x5a; 32];
    let mut state = SceneState::new();
    let accepted = [
        ProjectionEvent::control(1, 0, EventKind::PresenceReady, 0, b"Estou aqui."),
        ProjectionEvent::control(2, 0, EventKind::ModelLoading, 0, b""),
        ProjectionEvent::control(3, 0, EventKind::ModelReady, 0, b""),
        ProjectionEvent::control(4, 7, EventKind::AssistantStart, 0, b""),
        ProjectionEvent::control(5, 7, EventKind::AssistantToken, 1, b"Ola, "),
        ProjectionEvent::control(6, 7, EventKind::AssistantToken, 2, b"Guilherme."),
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
    let happy_path = accepted.into_iter().all(|event| state.apply(event).is_ok())
        && state.form == SceneForm::Materialized
        && state.model == ModelState::Ready
        && state.message.text.as_bytes() == b"Ola, Guilherme."
        && state.message.complete
        && state.receipt_count == 3;

    let before_duplicate = state;
    let duplicate_rejected = state.apply(accepted[0]) == Err(ProjectionError::DuplicateEvent);
    let transaction_preserved = state == before_duplicate;

    let mut stream = SceneState::new();
    let _ = stream.apply(ProjectionEvent::control(
        20,
        9,
        EventKind::AssistantStart,
        0,
        b"",
    ));
    let before_order = stream;
    let out_of_order_rejected = stream.apply(ProjectionEvent::control(
        21,
        9,
        EventKind::AssistantToken,
        2,
        b"fora",
    )) == Err(ProjectionError::TokenOutOfOrder)
        && stream == before_order;

    let mut cancelled = SceneState::new();
    let _ = cancelled.apply(ProjectionEvent::job(
        30,
        14,
        EventKind::JobStarted,
        1,
        b"Comecou.",
        evidence,
    ));
    let _ = cancelled.apply(ProjectionEvent::job(
        31,
        14,
        EventKind::JobCancelled,
        2,
        b"Cancelado.",
        evidence,
    ));
    let before_late = cancelled;
    let late_completion_rejected = cancelled.apply(ProjectionEvent::job(
        32,
        14,
        EventKind::JobCompleted,
        3,
        b"Tardio.",
        evidence,
    )) == Err(ProjectionError::JobTerminal)
        && cancelled == before_late;

    SelfTestSummary {
        happy_path,
        duplicate_rejected,
        out_of_order_rejected,
        late_completion_rejected,
        transaction_preserved,
    }
}
