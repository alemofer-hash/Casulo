export const WIRE_SCHEMA = "casulo.owner-ux-event/1.0";
export const CONTRACT_SCHEMA = "casulo.hosted-native-ux-contract/1.0";
export const MAX_EVENT_BYTES = 32 * 1024;

export const EVENT_KINDS = Object.freeze([
  "PRESENCE_READY", "MODEL_LOADING", "MODEL_READY", "INPUT_REQUEST",
  "ASSISTANT_START", "ASSISTANT_TOKEN", "ASSISTANT_END", "JOB_STARTED",
  "JOB_MILESTONE", "JOB_COMPLETED", "JOB_FAILED", "JOB_CANCELLED",
  "NOTICE", "RECOVERABLE_ERROR",
]);

const JOB_KINDS = new Set([
  "JOB_STARTED", "JOB_MILESTONE", "JOB_COMPLETED", "JOB_FAILED", "JOB_CANCELLED",
]);
const TERMINAL_JOB_KINDS = new Set(["JOB_COMPLETED", "JOB_FAILED", "JOB_CANCELLED"]);
const FORBIDDEN_PROGRESS = new Set(["progress_percent", "percentage", "eta", "fake_progress"]);
const SHA256 = /^[0-9a-f]{64}$/;
const ZERO_SHA256 = "0".repeat(64);

/** @typedef {{schema:string,event_id:string,kind:string,payload:Record<string,unknown>,source_event_ids:string[],occurred_at:string,event_hash:string}} ExperienceEvent */
/** @typedef {{id:string, text:string, complete:boolean}} AssistantMessage */
/** @typedef {{id:string, status:string, summary:string, evidence:string, milestones:Array<{summary:string,evidence:string}>}} JobView */

export function createInitialState() {
  return {
    presence: false,
    model: "ABSENT",
    form: "SILENCE",
    notice: "Abrindo um espaço silencioso para criar.",
    activeTurn: null,
    nextTokenSequence: 1,
    messages: /** @type {AssistantMessage[]} */ ([]),
    jobs: /** @type {JobView[]} */ ([]),
    seenEventIds: /** @type {string[]} */ ([]),
    lastEvent: /** @type {ExperienceEvent | null} */ (null),
    recoverableError: null,
  };
}

/** @param {unknown} input */
export function validateEventStructure(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("evento precisa ser objeto");
  const event = /** @type {Record<string, unknown>} */ (input);
  if (event.schema !== WIRE_SCHEMA) throw new Error("schema UX incompatível");
  if (typeof event.event_id !== "string" || !event.event_id) throw new Error("event_id ausente");
  if (typeof event.kind !== "string" || !EVENT_KINDS.includes(event.kind)) throw new Error("kind UX inválido");
  if (!event.payload || typeof event.payload !== "object" || Array.isArray(event.payload)) throw new Error("payload UX inválido");
  if (!Array.isArray(event.source_event_ids) || event.source_event_ids.length === 0 || event.source_event_ids.some((id) => typeof id !== "string" || !id)) throw new Error("proveniência UX ausente");
  if (typeof event.occurred_at !== "string" || !event.occurred_at) throw new Error("timestamp UX ausente");
  if (typeof event.event_hash !== "string" || !SHA256.test(event.event_hash)) throw new Error("hash UX inválido");
  const payload = /** @type {Record<string, unknown>} */ (event.payload);
  for (const key of Object.keys(payload)) if (FORBIDDEN_PROGRESS.has(key)) throw new Error("progresso fabricado é proibido");
  if (["ASSISTANT_START", "ASSISTANT_TOKEN", "ASSISTANT_END"].includes(event.kind) && (typeof payload.turn_id !== "string" || !payload.turn_id)) throw new Error("turn_id ausente");
  if (event.kind === "ASSISTANT_TOKEN") {
    if (typeof payload.text !== "string" || !payload.text || payload.text.length > 8192) throw new Error("token inválido");
    if (!Number.isInteger(payload.sequence) || Number(payload.sequence) < 1) throw new Error("sequência inválida");
  }
  if (JOB_KINDS.has(event.kind)) {
    if (typeof payload.job_id !== "string" || !payload.job_id || typeof payload.summary !== "string" || !payload.summary.trim()) throw new Error("job sem identidade ou resumo");
    if (typeof payload.evidence_sha256 !== "string" || !SHA256.test(payload.evidence_sha256) || payload.evidence_sha256 === ZERO_SHA256) throw new Error("job sem evidência SHA-256");
  }
  return /** @type {ExperienceEvent} */ (input);
}

/** @param {ReturnType<typeof createInitialState>} state @param {unknown} input */
export function reduceExperience(state, input) {
  const event = validateEventStructure(input);
  if (state.seenEventIds.includes(event.event_id)) throw new Error("evento UX duplicado");
  const payload = event.payload;
  const next = {
    ...state,
    messages: state.messages.map((message) => ({ ...message })),
    jobs: state.jobs.map((job) => ({ ...job, milestones: job.milestones.map((item) => ({ ...item })) })),
    seenEventIds: [...state.seenEventIds, event.event_id],
    lastEvent: event,
  };

  switch (event.kind) {
    case "PRESENCE_READY":
      next.presence = true;
      next.form = "PRESENCE";
      next.notice = String(payload.text || "Estou aqui.");
      break;
    case "MODEL_LOADING":
      if (next.model !== "ABSENT") throw new Error("transição de modelo inválida");
      next.model = "LOADING";
      next.notice = "A inteligência local está despertando. Você já pode começar.";
      break;
    case "MODEL_READY":
      if (next.model !== "LOADING") throw new Error("MODEL_READY sem MODEL_LOADING");
      next.model = "READY";
      next.notice = "Presença local pronta.";
      break;
    case "INPUT_REQUEST":
      next.form = "LISTENING";
      next.notice = String(payload.prompt || "Conte do seu jeito.");
      break;
    case "ASSISTANT_START": {
      if (next.activeTurn !== null) throw new Error("turno assistente já ativo");
      const turnId = String(payload.turn_id);
      next.activeTurn = turnId;
      next.nextTokenSequence = 1;
      next.form = "THINKING";
      next.messages.push({ id: turnId, text: "", complete: false });
      break;
    }
    case "ASSISTANT_TOKEN": {
      if (next.activeTurn !== String(payload.turn_id)) throw new Error("token fora do turno ativo");
      if (Number(payload.sequence) !== next.nextTokenSequence) throw new Error("token fora de ordem");
      const message = next.messages.find((item) => item.id === next.activeTurn);
      if (!message) throw new Error("mensagem ativa ausente");
      message.text += String(payload.text);
      next.nextTokenSequence += 1;
      next.form = "CONVERSATION";
      break;
    }
    case "ASSISTANT_END": {
      if (next.activeTurn !== String(payload.turn_id)) throw new Error("fim de turno sem stream ativo");
      const message = next.messages.find((item) => item.id === next.activeTurn);
      if (!message) throw new Error("mensagem terminal ausente");
      message.complete = true;
      next.activeTurn = null;
      next.form = "PRESENCE";
      break;
    }
    case "JOB_STARTED": {
      const jobId = String(payload.job_id);
      if (next.jobs.some((job) => job.id === jobId)) throw new Error("job UX duplicado");
      next.jobs.push({ id: jobId, status: "ACTIVE", summary: String(payload.summary), evidence: String(payload.evidence_sha256), milestones: [] });
      next.form = "FIRST_FORM";
      next.notice = String(payload.summary);
      break;
    }
    case "JOB_MILESTONE": {
      const job = next.jobs.find((item) => item.id === String(payload.job_id));
      if (!job || job.status !== "ACTIVE") throw new Error("milestone sem job ativo");
      job.summary = String(payload.summary);
      job.evidence = String(payload.evidence_sha256);
      job.milestones.push({ summary: job.summary, evidence: job.evidence });
      next.form = "FORMATION";
      next.notice = job.summary;
      break;
    }
    case "JOB_COMPLETED":
    case "JOB_FAILED":
    case "JOB_CANCELLED": {
      const job = next.jobs.find((item) => item.id === String(payload.job_id));
      if (!job || job.status !== "ACTIVE") throw new Error("terminal sem job ativo");
      job.status = event.kind.replace("JOB_", "");
      job.summary = String(payload.summary);
      job.evidence = String(payload.evidence_sha256);
      next.form = event.kind === "JOB_COMPLETED" ? "MATERIALIZED" : event.kind === "JOB_CANCELLED" ? "CANCELLED" : "RECOVERABLE_FAILURE";
      next.notice = job.summary;
      if (event.kind === "JOB_FAILED") next.recoverableError = job.summary;
      break;
    }
    case "NOTICE":
      next.notice = String(payload.text || "Aviso do Casulo.");
      break;
    case "RECOVERABLE_ERROR":
      next.form = "RECOVERABLE_FAILURE";
      next.recoverableError = String(payload.text || "Algo parou, mas o que já existe foi preservado.");
      next.notice = next.recoverableError;
      break;
  }
  return next;
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function sha256Hex(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** Creates design-only events. It is intentionally unavailable to the Rust runtime bridge. */
export async function createSyntheticEvent(index, kind, payload) {
  const unsigned = {
    schema: WIRE_SCHEMA,
    event_id: `design:${index}`,
    kind,
    payload,
    source_event_ids: [`synthetic-design-tape:${index}`],
    occurred_at: `2026-08-20T12:00:${String(index).padStart(2, "0")}-03:00`,
  };
  return { ...unsigned, event_hash: await sha256Hex(`${canonical(unsigned)}\n`) };
}

export async function buildDesignTape() {
  const evidence = (char) => char.repeat(64);
  const rows = [
    ["PRESENCE_READY", { text: "Estou aqui. O que apareceu na sua cabeça?" }],
    ["MODEL_LOADING", { model: "local-owner" }],
    ["MODEL_READY", { model: "local-owner" }],
    ["ASSISTANT_START", { turn_id: "turn:design" }],
    ["ASSISTANT_TOKEN", { turn_id: "turn:design", sequence: 1, text: "Entendi a imagem: " }],
    ["ASSISTANT_TOKEN", { turn_id: "turn:design", sequence: 2, text: "um lugar calmo que transforma ideias " }],
    ["ASSISTANT_TOKEN", { turn_id: "turn:design", sequence: 3, text: "em algo que você possa abrir e usar." }],
    ["ASSISTANT_END", { turn_id: "turn:design", finish_reason: "stop" }],
    ["JOB_STARTED", { job_id: "job:design", summary: "A ideia foi reconhecida e preservada.", evidence_sha256: evidence("a") }],
    ["JOB_MILESTONE", { job_id: "job:design", summary: "A primeira estrutura ganhou forma.", evidence_sha256: evidence("b") }],
    ["JOB_MILESTONE", { job_id: "job:design", summary: "A simulação confirmou o comportamento combinado.", evidence_sha256: evidence("c") }],
    ["JOB_COMPLETED", { job_id: "job:design", summary: "A criação está pronta para abrir.", evidence_sha256: evidence("d") }],
  ];
  return Promise.all(rows.map(([kind, payload], index) => createSyntheticEvent(index + 1, String(kind), payload)));
}

export { TERMINAL_JOB_KINDS };
