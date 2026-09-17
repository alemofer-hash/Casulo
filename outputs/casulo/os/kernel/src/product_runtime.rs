//! Bounded Native implementation of the Hosted/Native UX contract.
//!
//! This module does not claim native speech, model inference or the hosted
//! renderer. It proves the product control plane that those adapters consume:
//! presence priority, ordered assistant streams, evidence-bearing jobs and
//! fail-closed cancellation.

pub const CONTRACT_SCHEMA: &str = "casulo.hosted-native-ux-contract/1.0";
pub const WIRE_SCHEMA: &str = "casulo.owner-ux-event/1.0";
pub const CONTRACT_SHA256: &str =
    "4d209cce708d843ffef50ac606ba199151be39eb9ecfff9c2c9fae233d24bcb9";
pub const MAX_EVENT_BYTES: usize = 32 * 1024;
pub const MAX_QUEUE_EVENTS: usize = 16;
const MAX_SEEN_EVENTS: usize = 32;
const MAX_JOBS: usize = 4;

pub const CONTRACT_EVENT_KINDS: [&str; 14] = [
    "PRESENCE_READY",
    "MODEL_LOADING",
    "MODEL_READY",
    "INPUT_REQUEST",
    "ASSISTANT_START",
    "ASSISTANT_TOKEN",
    "ASSISTANT_END",
    "JOB_STARTED",
    "JOB_MILESTONE",
    "JOB_COMPLETED",
    "JOB_FAILED",
    "JOB_CANCELLED",
    "NOTICE",
    "RECOVERABLE_ERROR",
];

pub const CONTRACT_PRIORITIES: [&str; 5] = ["PRESENCE", "FLOW", "SYSTEM", "BACKGROUND", "AUDIT"];

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
    const fn is_job(self) -> bool {
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

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum EventPriority {
    Presence = 0,
    Flow = 1,
    System = 2,
    Background = 3,
    Audit = 4,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProductEvent {
    pub event_id: u32,
    pub subject_id: u32,
    pub kind: EventKind,
    pub priority: EventPriority,
    pub sequence: u16,
    pub evidence_sha256: [u8; 32],
}

impl ProductEvent {
    pub const fn control(
        event_id: u32,
        subject_id: u32,
        kind: EventKind,
        priority: EventPriority,
        sequence: u16,
    ) -> Self {
        Self {
            event_id,
            subject_id,
            kind,
            priority,
            sequence,
            evidence_sha256: [0; 32],
        }
    }

    pub const fn evidenced_job(
        event_id: u32,
        job_id: u32,
        kind: EventKind,
        sequence: u16,
        evidence_sha256: [u8; 32],
    ) -> Self {
        Self {
            event_id,
            subject_id: job_id,
            kind,
            priority: EventPriority::Background,
            sequence,
            evidence_sha256,
        }
    }

    fn has_evidence(self) -> bool {
        self.evidence_sha256.iter().any(|byte| *byte != 0)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ContractError {
    DuplicateEvent,
    InvalidModelTransition,
    StreamAlreadyActive,
    StreamNotActive,
    TokenOutOfOrder,
    MissingEvidence,
    JobAlreadyExists,
    JobNotStarted,
    JobTerminal,
    JobSequence,
    CapacityExceeded,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ModelState {
    Absent,
    Loading,
    Ready,
}

#[derive(Clone, Copy)]
struct StreamTracker {
    turn_id: u32,
    next_sequence: u16,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum JobState {
    Active,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Clone, Copy)]
struct JobTracker {
    job_id: u32,
    state: JobState,
    last_sequence: u16,
}

pub struct ContractValidator {
    model: ModelState,
    stream: Option<StreamTracker>,
    jobs: [Option<JobTracker>; MAX_JOBS],
    seen: [u32; MAX_SEEN_EVENTS],
    seen_len: usize,
}

impl ContractValidator {
    pub const fn new() -> Self {
        Self {
            model: ModelState::Absent,
            stream: None,
            jobs: [None; MAX_JOBS],
            seen: [0; MAX_SEEN_EVENTS],
            seen_len: 0,
        }
    }

    pub fn accept(&mut self, event: ProductEvent) -> Result<(), ContractError> {
        if self.seen[..self.seen_len].contains(&event.event_id) {
            return Err(ContractError::DuplicateEvent);
        }
        if self.seen_len == MAX_SEEN_EVENTS {
            return Err(ContractError::CapacityExceeded);
        }
        if event.kind.is_job() && !event.has_evidence() {
            return Err(ContractError::MissingEvidence);
        }
        self.accept_kind(event)?;
        self.seen[self.seen_len] = event.event_id;
        self.seen_len += 1;
        Ok(())
    }

    fn accept_kind(&mut self, event: ProductEvent) -> Result<(), ContractError> {
        match event.kind {
            EventKind::ModelLoading => {
                if self.model != ModelState::Absent {
                    return Err(ContractError::InvalidModelTransition);
                }
                self.model = ModelState::Loading;
            }
            EventKind::ModelReady => {
                if self.model != ModelState::Loading {
                    return Err(ContractError::InvalidModelTransition);
                }
                self.model = ModelState::Ready;
            }
            EventKind::AssistantStart => {
                if self.stream.is_some() {
                    return Err(ContractError::StreamAlreadyActive);
                }
                self.stream = Some(StreamTracker {
                    turn_id: event.subject_id,
                    next_sequence: 1,
                });
            }
            EventKind::AssistantToken => {
                let Some(stream) = self.stream.as_mut() else {
                    return Err(ContractError::StreamNotActive);
                };
                if stream.turn_id != event.subject_id || event.sequence != stream.next_sequence {
                    return Err(ContractError::TokenOutOfOrder);
                }
                stream.next_sequence = stream.next_sequence.saturating_add(1);
            }
            EventKind::AssistantEnd => {
                let Some(stream) = self.stream else {
                    return Err(ContractError::StreamNotActive);
                };
                if stream.turn_id != event.subject_id {
                    return Err(ContractError::StreamNotActive);
                }
                self.stream = None;
            }
            EventKind::JobStarted => self.start_job(event)?,
            EventKind::JobMilestone
            | EventKind::JobCompleted
            | EventKind::JobFailed
            | EventKind::JobCancelled => self.advance_job(event)?,
            EventKind::PresenceReady
            | EventKind::InputRequest
            | EventKind::Notice
            | EventKind::RecoverableError => {}
        }
        Ok(())
    }

    fn start_job(&mut self, event: ProductEvent) -> Result<(), ContractError> {
        if self
            .jobs
            .iter()
            .flatten()
            .any(|job| job.job_id == event.subject_id)
        {
            return Err(ContractError::JobAlreadyExists);
        }
        if event.sequence != 1 {
            return Err(ContractError::JobSequence);
        }
        let Some(slot) = self.jobs.iter_mut().find(|slot| slot.is_none()) else {
            return Err(ContractError::CapacityExceeded);
        };
        *slot = Some(JobTracker {
            job_id: event.subject_id,
            state: JobState::Active,
            last_sequence: 1,
        });
        Ok(())
    }

    fn advance_job(&mut self, event: ProductEvent) -> Result<(), ContractError> {
        let Some(job) = self
            .jobs
            .iter_mut()
            .flatten()
            .find(|job| job.job_id == event.subject_id)
        else {
            return Err(ContractError::JobNotStarted);
        };
        if job.state != JobState::Active {
            return Err(ContractError::JobTerminal);
        }
        if event.sequence != job.last_sequence.saturating_add(1) {
            return Err(ContractError::JobSequence);
        }
        job.last_sequence = event.sequence;
        job.state = match event.kind {
            EventKind::JobCompleted => JobState::Completed,
            EventKind::JobFailed => JobState::Failed,
            EventKind::JobCancelled => JobState::Cancelled,
            EventKind::JobMilestone => JobState::Active,
            _ => return Err(ContractError::JobSequence),
        };
        Ok(())
    }
}

#[derive(Clone, Copy)]
struct QueuedEvent {
    event: ProductEvent,
    insertion_order: u16,
}

pub struct NativeEventLoop {
    entries: [Option<QueuedEvent>; MAX_QUEUE_EVENTS],
    next_order: u16,
}

impl NativeEventLoop {
    pub const fn new() -> Self {
        Self {
            entries: [None; MAX_QUEUE_EVENTS],
            next_order: 0,
        }
    }

    pub fn push(&mut self, event: ProductEvent) -> Result<(), ContractError> {
        let Some(slot) = self.entries.iter_mut().find(|slot| slot.is_none()) else {
            return Err(ContractError::CapacityExceeded);
        };
        *slot = Some(QueuedEvent {
            event,
            insertion_order: self.next_order,
        });
        self.next_order = self.next_order.wrapping_add(1);
        Ok(())
    }

    pub fn pop(&mut self) -> Option<ProductEvent> {
        let index = self
            .entries
            .iter()
            .enumerate()
            .filter_map(|(index, queued)| queued.map(|queued| (index, queued)))
            .min_by_key(|(_, queued)| (queued.event.priority, queued.insertion_order))
            .map(|(index, _)| index)?;
        self.entries[index].take().map(|queued| queued.event)
    }
}

pub struct ProductRuntimeSummary {
    pub model_lifecycle: bool,
    pub assistant_stream: bool,
    pub job_lifecycle: bool,
    pub late_completion_rejected: bool,
    pub presence_priority: bool,
    pub bounded_queue: bool,
}

impl ProductRuntimeSummary {
    pub fn passed(&self) -> bool {
        self.model_lifecycle
            && self.assistant_stream
            && self.job_lifecycle
            && self.late_completion_rejected
            && self.presence_priority
            && self.bounded_queue
    }
}

pub fn self_test() -> ProductRuntimeSummary {
    let mut validator = ContractValidator::new();
    let model_lifecycle = validator
        .accept(ProductEvent::control(
            1,
            0,
            EventKind::PresenceReady,
            EventPriority::Presence,
            0,
        ))
        .and_then(|_| {
            validator.accept(ProductEvent::control(
                2,
                0,
                EventKind::ModelLoading,
                EventPriority::System,
                0,
            ))
        })
        .and_then(|_| {
            validator.accept(ProductEvent::control(
                3,
                0,
                EventKind::ModelReady,
                EventPriority::System,
                0,
            ))
        })
        .is_ok();

    let assistant_stream = validator
        .accept(ProductEvent::control(
            4,
            7,
            EventKind::AssistantStart,
            EventPriority::Presence,
            0,
        ))
        .and_then(|_| {
            validator.accept(ProductEvent::control(
                5,
                7,
                EventKind::AssistantToken,
                EventPriority::Presence,
                1,
            ))
        })
        .and_then(|_| {
            validator.accept(ProductEvent::control(
                6,
                7,
                EventKind::AssistantToken,
                EventPriority::Presence,
                2,
            ))
        })
        .and_then(|_| {
            validator.accept(ProductEvent::control(
                7,
                7,
                EventKind::AssistantEnd,
                EventPriority::Presence,
                0,
            ))
        })
        .is_ok();

    let evidence = [0x5a; 32];
    let cancelled_lifecycle = validator
        .accept(ProductEvent::evidenced_job(
            8,
            11,
            EventKind::JobStarted,
            1,
            evidence,
        ))
        .and_then(|_| {
            validator.accept(ProductEvent::evidenced_job(
                9,
                11,
                EventKind::JobMilestone,
                2,
                evidence,
            ))
        })
        .and_then(|_| {
            validator.accept(ProductEvent::evidenced_job(
                10,
                11,
                EventKind::JobCancelled,
                3,
                evidence,
            ))
        })
        .is_ok();
    let late_completion_rejected = validator.accept(ProductEvent::evidenced_job(
        11,
        11,
        EventKind::JobCompleted,
        4,
        evidence,
    )) == Err(ContractError::JobTerminal);
    let failed_lifecycle = validator
        .accept(ProductEvent::evidenced_job(
            12,
            12,
            EventKind::JobStarted,
            1,
            evidence,
        ))
        .and_then(|_| {
            validator.accept(ProductEvent::evidenced_job(
                13,
                12,
                EventKind::JobFailed,
                2,
                evidence,
            ))
        })
        .is_ok();
    let job_lifecycle = cancelled_lifecycle && failed_lifecycle;

    let mut queue = NativeEventLoop::new();
    let background = ProductEvent::control(
        20,
        1,
        EventKind::RecoverableError,
        EventPriority::Background,
        0,
    );
    let flow = ProductEvent::control(21, 1, EventKind::Notice, EventPriority::Flow, 0);
    let presence =
        ProductEvent::control(22, 1, EventKind::InputRequest, EventPriority::Presence, 0);
    let presence_priority = queue.push(background).is_ok()
        && queue.push(flow).is_ok()
        && queue.push(presence).is_ok()
        && queue.pop() == Some(presence)
        && queue.pop() == Some(flow)
        && queue.pop() == Some(background);

    let mut bounded = NativeEventLoop::new();
    let mut filled = true;
    for index in 0..MAX_QUEUE_EVENTS {
        filled &= bounded
            .push(ProductEvent::control(
                100 + index as u32,
                0,
                EventKind::Notice,
                EventPriority::Audit,
                0,
            ))
            .is_ok();
    }
    let bounded_queue = filled
        && bounded.push(ProductEvent::control(
            999,
            0,
            EventKind::Notice,
            EventPriority::Audit,
            0,
        )) == Err(ContractError::CapacityExceeded);

    ProductRuntimeSummary {
        model_lifecycle,
        assistant_stream,
        job_lifecycle,
        late_completion_rejected,
        presence_priority,
        bounded_queue,
    }
}
