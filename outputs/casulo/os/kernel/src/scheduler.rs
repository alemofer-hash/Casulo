//! Bounded in-kernel task manager and deterministic G4 policy comparison.
//!
//! Every dispatch crosses to ring 3 and returns through the YIELD syscall. The
//! policy tick is an operation-count unit from the frozen host reference, not
//! wall-clock time and not an energy measurement.

use crate::memory::UserAddressSpace;
use crate::process::{self, UserTrap};

pub const REFERENCE_VECTOR_SHA256: &str =
    "c76b1fd397b2a5e84fc6443c027e3d9545ee9dca78f005dfb5c8c962035ae766";
pub const AUDIT_INTERVAL: u64 = 4;
const MAX_TASKS: usize = 16;
const MAX_EVENTS: usize = 32;
const MAX_READY: usize = 64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Policy {
    Conventional,
    Semantic,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SemanticClass {
    Flow,
    System,
    AttractorAudit,
    Retry,
    LowConfidence,
    Quarantine,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum TaskId {
    NoiseSystem,
    NoiseRetry,
    FlowA,
    FlowB,
    Audit,
    LowConfidence,
    Flow1,
    Flow2,
    Flow3,
    Flow4,
    Flow5,
    Flow6,
    PersistentFlow,
    FiniteFlow,
    FiniteSystem,
    FiniteRetry,
    FiniteLow,
    BadIntegrity,
    BadPermissions,
    BadQuality,
    BadIsolation,
    RequestedQuarantine,
}

#[derive(Clone, Copy)]
struct Task {
    id: TaskId,
    class: SemanticClass,
    budget: u64,
    remaining: u64,
    priority: i8,
    deadline: Option<u64>,
    integrity: bool,
    permissions: bool,
    quality: bool,
    isolation: bool,
    sequence: u16,
    admitted: SemanticClass,
}

impl Task {
    const fn valid(
        id: TaskId,
        class: SemanticClass,
        budget: u64,
        priority: i8,
        deadline: Option<u64>,
    ) -> Self {
        Self {
            id,
            class,
            budget,
            remaining: budget,
            priority,
            deadline,
            integrity: true,
            permissions: true,
            quality: true,
            isolation: true,
            sequence: 0,
            admitted: class,
        }
    }

    const fn invalid(id: TaskId, class: SemanticClass, gate: u8) -> Self {
        let mut task = Self::valid(id, class, 1, 0, None);
        task.integrity = gate != 1;
        task.permissions = gate != 2;
        task.quality = gate != 3;
        task.isolation = gate != 4;
        task
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Decision {
    ConventionalFifo,
    SemanticPriority,
    PeriodicAudit,
}

#[derive(Clone, Copy)]
struct Event {
    tick: u64,
    task: TaskId,
    class: SemanticClass,
    decision: Decision,
    remaining: u64,
    priority: i8,
    deadline: Option<u64>,
    deadline_missed: bool,
    selection_checks: u64,
}

struct Manager {
    policy: Policy,
    tasks: [Option<Task>; MAX_TASKS],
    task_count: usize,
    ready: [usize; MAX_READY],
    ready_len: usize,
    events: [Option<Event>; MAX_EVENTS],
    event_count: usize,
    tick: u64,
    quarantine_count: u64,
    quarantine_dispatches: u64,
    yield_returns: u64,
    ring3_ok: bool,
}

impl Manager {
    const fn new(policy: Policy) -> Self {
        Self {
            policy,
            tasks: [None; MAX_TASKS],
            task_count: 0,
            ready: [0; MAX_READY],
            ready_len: 0,
            events: [None; MAX_EVENTS],
            event_count: 0,
            tick: 0,
            quarantine_count: 0,
            quarantine_dispatches: 0,
            yield_returns: 0,
            ring3_ok: true,
        }
    }

    fn admit(&mut self, mut task: Task) {
        assert!(self.task_count < MAX_TASKS && task.budget > 0);
        task.sequence = self.task_count as u16;
        let hard_gate = task.integrity && task.permissions && task.quality && task.isolation;
        task.admitted = if hard_gate && task.class != SemanticClass::Quarantine {
            task.class
        } else {
            SemanticClass::Quarantine
        };
        let index = self.task_count;
        self.tasks[index] = Some(task);
        self.task_count += 1;
        if task.admitted == SemanticClass::Quarantine {
            self.quarantine_count += 1;
        } else if self.policy == Policy::Conventional {
            self.push_ready(index);
        }
    }

    fn push_ready(&mut self, index: usize) {
        assert!(self.ready_len < MAX_READY);
        self.ready[self.ready_len] = index;
        self.ready_len += 1;
    }

    fn pop_ready(&mut self) -> Option<usize> {
        if self.ready_len == 0 {
            return None;
        }
        let first = self.ready[0];
        self.ready.copy_within(1..self.ready_len, 0);
        self.ready_len -= 1;
        Some(first)
    }

    fn run(&mut self, maximum_ticks: u64, address_space: UserAddressSpace) {
        for _ in 0..maximum_ticks {
            let Some((index, decision, selection_checks)) = self.select() else {
                break;
            };
            let slice = process::run_yield_slice(address_space);
            let yielded = slice.separate_cr3
                && slice.trap == UserTrap::Yield
                && slice.yield_kernel_returns == 1;
            self.ring3_ok &= yielded;
            self.yield_returns += u64::from(yielded);

            let task = self.tasks[index].as_mut().expect("selected task missing");
            assert!(task.admitted != SemanticClass::Quarantine && task.remaining > 0);
            task.remaining -= 1;
            self.tick += 1;
            let event = Event {
                tick: self.tick,
                task: task.id,
                class: task.class,
                decision,
                remaining: task.remaining,
                priority: task.priority,
                deadline: task.deadline,
                deadline_missed: task.deadline.is_some_and(|deadline| self.tick > deadline),
                selection_checks,
            };
            assert!(self.event_count < MAX_EVENTS);
            self.events[self.event_count] = Some(event);
            self.event_count += 1;
            if self.policy == Policy::Conventional && task.remaining > 0 {
                self.push_ready(index);
            }
        }
    }

    fn select(&mut self) -> Option<(usize, Decision, u64)> {
        if self.policy == Policy::Conventional {
            return self
                .pop_ready()
                .map(|index| (index, Decision::ConventionalFifo, 1));
        }
        let mut checks = 1;
        if (self.tick + 1).is_multiple_of(AUDIT_INTERVAL)
            && let Some((index, rank_checks)) = self.best_in_class(SemanticClass::AttractorAudit)
        {
            return Some((index, Decision::PeriodicAudit, checks + rank_checks));
        }
        for class in [
            SemanticClass::Flow,
            SemanticClass::System,
            SemanticClass::Retry,
            SemanticClass::LowConfidence,
            SemanticClass::AttractorAudit,
        ] {
            checks += 1;
            if let Some((index, rank_checks)) = self.best_in_class(class) {
                return Some((index, Decision::SemanticPriority, checks + rank_checks));
            }
        }
        None
    }

    fn best_in_class(&self, class: SemanticClass) -> Option<(usize, u64)> {
        let mut best: Option<usize> = None;
        let mut count = 0u64;
        for index in 0..self.task_count {
            let task = self.tasks[index].expect("bounded task hole");
            if task.admitted != class || task.remaining == 0 {
                continue;
            }
            count += 1;
            if best.is_none_or(|current| rank_before(task, self.tasks[current].unwrap())) {
                best = Some(index);
            }
        }
        best.map(|index| (index, count))
    }

    fn event(&self, index: usize) -> Event {
        self.events[index].expect("missing event")
    }
}

fn rank_before(left: Task, right: Task) -> bool {
    let left_deadline = left.deadline.unwrap_or(u64::MAX);
    let right_deadline = right.deadline.unwrap_or(u64::MAX);
    (left_deadline, -left.priority, left.sequence)
        < (right_deadline, -right.priority, right.sequence)
}

pub struct G4Summary {
    pub gate_pass: bool,
    pub help_conventional_p95: u64,
    pub help_semantic_p95: u64,
    pub no_help_conventional_p95: u64,
    pub no_help_semantic_p95: u64,
    pub flow_dispatches: u64,
    pub audit_dispatches: u64,
    pub audit_max_gap: u64,
    pub quarantine_count: u64,
    pub quarantine_dispatches: u64,
    pub yield_kernel_returns: u64,
    pub ring3_dispatches: u64,
    pub reference_trace_match: bool,
    pub finite_work_completed: bool,
}

pub fn run_g4(address_space: UserAddressSpace) -> G4Summary {
    let mut conventional_help = help_manager(Policy::Conventional);
    conventional_help.run(24, address_space);
    let mut semantic_help = help_manager(Policy::Semantic);
    semantic_help.run(24, address_space);
    let mut conventional_no_help = no_help_manager(Policy::Conventional);
    conventional_no_help.run(6, address_space);
    let mut semantic_no_help = no_help_manager(Policy::Semantic);
    semantic_no_help.run(6, address_space);

    let reference_trace_match = compare_help(&conventional_help, Policy::Conventional)
        && compare_help(&semantic_help, Policy::Semantic)
        && compare_no_help(&conventional_no_help, Policy::Conventional)
        && compare_no_help(&semantic_no_help, Policy::Semantic);

    let mut starvation = Manager::new(Policy::Semantic);
    starvation.admit(Task::valid(
        TaskId::PersistentFlow,
        SemanticClass::Flow,
        20,
        0,
        None,
    ));
    starvation.admit(Task::valid(
        TaskId::Audit,
        SemanticClass::AttractorAudit,
        4,
        0,
        None,
    ));
    starvation.run(20, address_space);
    let mut previous = 0;
    let mut audit_max_gap = 0;
    let mut audit_dispatches = 0;
    for index in 0..starvation.event_count {
        let event = starvation.event(index);
        if event.class == SemanticClass::AttractorAudit {
            audit_max_gap = audit_max_gap.max(event.tick - previous);
            previous = event.tick;
            audit_dispatches += 1;
        }
    }

    let mut finite = Manager::new(Policy::Semantic);
    for task in finite_tasks() {
        finite.admit(task);
    }
    finite.run(10, address_space);
    let finite_work_completed = (0..finite.task_count).all(|index| {
        finite.tasks[index]
            .is_some_and(|task| task.admitted == SemanticClass::Quarantine || task.remaining == 0)
    });

    let mut safety = Manager::new(Policy::Semantic);
    safety.admit(Task::invalid(TaskId::BadIntegrity, SemanticClass::Flow, 1));
    safety.admit(Task::invalid(
        TaskId::BadPermissions,
        SemanticClass::System,
        2,
    ));
    safety.admit(Task::invalid(TaskId::BadQuality, SemanticClass::Retry, 3));
    safety.admit(Task::invalid(
        TaskId::BadIsolation,
        SemanticClass::LowConfidence,
        4,
    ));
    safety.admit(Task::valid(
        TaskId::RequestedQuarantine,
        SemanticClass::Quarantine,
        1,
        0,
        None,
    ));
    safety.run(8, address_space);

    let help_conventional_p95 = flow_p95(&conventional_help);
    let help_semantic_p95 = flow_p95(&semantic_help);
    let no_help_conventional_p95 = flow_p95(&conventional_no_help);
    let no_help_semantic_p95 = flow_p95(&semantic_no_help);
    let managers = [
        &conventional_help,
        &semantic_help,
        &conventional_no_help,
        &semantic_no_help,
        &starvation,
        &finite,
    ];
    let ring3_dispatches = managers
        .iter()
        .map(|manager| manager.event_count as u64)
        .sum();
    let yield_kernel_returns = managers.iter().map(|manager| manager.yield_returns).sum();
    let ring3_ok = managers.iter().all(|manager| manager.ring3_ok);
    let quarantine_dispatches = managers
        .iter()
        .map(|manager| manager.quarantine_dispatches)
        .sum::<u64>()
        + safety.quarantine_dispatches;
    let gate_pass = reference_trace_match
        && help_semantic_p95 == 5
        && help_conventional_p95 == 10
        && no_help_semantic_p95 == 6
        && no_help_conventional_p95 == 6
        && audit_dispatches == 4
        && audit_max_gap <= AUDIT_INTERVAL
        && finite_work_completed
        && safety.quarantine_count == 5
        && safety.event_count == 0
        && quarantine_dispatches == 0
        && ring3_ok
        && yield_kernel_returns == ring3_dispatches;
    G4Summary {
        gate_pass,
        help_conventional_p95,
        help_semantic_p95,
        no_help_conventional_p95,
        no_help_semantic_p95,
        flow_dispatches: semantic_help
            .events
            .iter()
            .flatten()
            .filter(|event| event.class == SemanticClass::Flow)
            .count() as u64,
        audit_dispatches,
        audit_max_gap,
        quarantine_count: safety.quarantine_count,
        quarantine_dispatches,
        yield_kernel_returns,
        ring3_dispatches,
        reference_trace_match,
        finite_work_completed,
    }
}

fn help_manager(policy: Policy) -> Manager {
    let mut manager = Manager::new(policy);
    for task in [
        Task::valid(TaskId::NoiseSystem, SemanticClass::System, 8, 0, None),
        Task::valid(TaskId::NoiseRetry, SemanticClass::Retry, 8, 0, None),
        Task::valid(TaskId::FlowA, SemanticClass::Flow, 2, 4, Some(8)),
        Task::valid(TaskId::FlowB, SemanticClass::Flow, 2, 2, Some(10)),
        Task::valid(TaskId::Audit, SemanticClass::AttractorAudit, 2, 0, None),
        Task::valid(
            TaskId::LowConfidence,
            SemanticClass::LowConfidence,
            2,
            0,
            None,
        ),
    ] {
        manager.admit(task);
    }
    manager
}

fn no_help_manager(policy: Policy) -> Manager {
    let mut manager = Manager::new(policy);
    for id in [
        TaskId::Flow1,
        TaskId::Flow2,
        TaskId::Flow3,
        TaskId::Flow4,
        TaskId::Flow5,
        TaskId::Flow6,
    ] {
        manager.admit(Task::valid(id, SemanticClass::Flow, 1, 0, None));
    }
    manager
}

fn finite_tasks() -> [Task; 5] {
    [
        Task::valid(TaskId::FiniteFlow, SemanticClass::Flow, 2, 0, None),
        Task::valid(TaskId::FiniteSystem, SemanticClass::System, 2, 0, None),
        Task::valid(TaskId::FiniteRetry, SemanticClass::Retry, 2, 0, None),
        Task::valid(TaskId::FiniteLow, SemanticClass::LowConfidence, 2, 0, None),
        Task::valid(TaskId::Audit, SemanticClass::AttractorAudit, 2, 0, None),
    ]
}

fn flow_p95(manager: &Manager) -> u64 {
    manager
        .events
        .iter()
        .flatten()
        .filter(|event| event.class == SemanticClass::Flow && event.remaining == 0)
        .map(|event| event.tick)
        .max()
        .unwrap_or(0)
}

fn compare_help(manager: &Manager, policy: Policy) -> bool {
    const CONVENTIONAL: [TaskId; 24] = [
        TaskId::NoiseSystem,
        TaskId::NoiseRetry,
        TaskId::FlowA,
        TaskId::FlowB,
        TaskId::Audit,
        TaskId::LowConfidence,
        TaskId::NoiseSystem,
        TaskId::NoiseRetry,
        TaskId::FlowA,
        TaskId::FlowB,
        TaskId::Audit,
        TaskId::LowConfidence,
        TaskId::NoiseSystem,
        TaskId::NoiseRetry,
        TaskId::NoiseSystem,
        TaskId::NoiseRetry,
        TaskId::NoiseSystem,
        TaskId::NoiseRetry,
        TaskId::NoiseSystem,
        TaskId::NoiseRetry,
        TaskId::NoiseSystem,
        TaskId::NoiseRetry,
        TaskId::NoiseSystem,
        TaskId::NoiseRetry,
    ];
    const SEMANTIC: [TaskId; 24] = [
        TaskId::FlowA,
        TaskId::FlowA,
        TaskId::FlowB,
        TaskId::Audit,
        TaskId::FlowB,
        TaskId::NoiseSystem,
        TaskId::NoiseSystem,
        TaskId::Audit,
        TaskId::NoiseSystem,
        TaskId::NoiseSystem,
        TaskId::NoiseSystem,
        TaskId::NoiseSystem,
        TaskId::NoiseSystem,
        TaskId::NoiseSystem,
        TaskId::NoiseRetry,
        TaskId::NoiseRetry,
        TaskId::NoiseRetry,
        TaskId::NoiseRetry,
        TaskId::NoiseRetry,
        TaskId::NoiseRetry,
        TaskId::NoiseRetry,
        TaskId::NoiseRetry,
        TaskId::LowConfidence,
        TaskId::LowConfidence,
    ];
    const SEMANTIC_CHECKS: [u64; 24] = [
        4, 4, 3, 2, 3, 4, 4, 2, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 6, 6,
    ];
    let expected = if policy == Policy::Conventional {
        &CONVENTIONAL
    } else {
        &SEMANTIC
    };
    compare_trace(manager, expected, Some(&SEMANTIC_CHECKS))
}

fn compare_no_help(manager: &Manager, _policy: Policy) -> bool {
    const EXPECTED: [TaskId; 6] = [
        TaskId::Flow1,
        TaskId::Flow2,
        TaskId::Flow3,
        TaskId::Flow4,
        TaskId::Flow5,
        TaskId::Flow6,
    ];
    const SEMANTIC_CHECKS: [u64; 6] = [8, 7, 6, 5, 4, 3];
    compare_trace(manager, &EXPECTED, Some(&SEMANTIC_CHECKS))
}

fn compare_trace(manager: &Manager, expected: &[TaskId], semantic_checks: Option<&[u64]>) -> bool {
    if manager.event_count != expected.len() {
        return false;
    }
    let mut occurrences = [0u64; MAX_TASKS];
    for (index, expected_id) in expected.iter().enumerate() {
        let event = manager.event(index);
        let Some(task_index) = (0..manager.task_count).find(|candidate| {
            manager.tasks[*candidate].is_some_and(|task| task.id == *expected_id)
        }) else {
            return false;
        };
        occurrences[task_index] += 1;
        let task = manager.tasks[task_index].unwrap();
        let expected_remaining = task.budget - occurrences[task_index];
        let expected_decision = if manager.policy == Policy::Conventional {
            Decision::ConventionalFifo
        } else if task.class == SemanticClass::AttractorAudit
            && event.tick.is_multiple_of(AUDIT_INTERVAL)
        {
            Decision::PeriodicAudit
        } else {
            Decision::SemanticPriority
        };
        let expected_checks = if manager.policy == Policy::Conventional {
            1
        } else {
            semantic_checks.expect("semantic checks missing")[index]
        };
        if event.task != *expected_id
            || event.tick != index as u64 + 1
            || event.class != task.class
            || event.decision != expected_decision
            || event.remaining != expected_remaining
            || event.priority != task.priority
            || event.deadline != task.deadline
            || event.deadline_missed != task.deadline.is_some_and(|d| event.tick > d)
            || event.selection_checks != expected_checks
        {
            return false;
        }
    }
    true
}
