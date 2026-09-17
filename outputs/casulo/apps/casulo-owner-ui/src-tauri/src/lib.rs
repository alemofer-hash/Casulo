use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::{Emitter, State};

const CONTRACT_SCHEMA: &str = "casulo.hosted-native-ux-contract/1.0";
const WIRE_SCHEMA: &str = "casulo.owner-ux-event/1.0";
const CONTRACT_SHA256: &str = "4d209cce708d843ffef50ac606ba199151be39eb9ecfff9c2c9fae233d24bcb9";
const EVENT_PREFIX: &str = "CASULO_UX_EVENT ";
const MAX_EVENT_BYTES: usize = 32 * 1024;
const EVENT_CHANNEL: &str = "casulo://experience";
const REJECTION_CHANNEL: &str = "casulo://bridge-rejection";

#[derive(Clone, Debug, Deserialize, Serialize)]
struct ExperienceEvent {
    schema: String,
    event_id: String,
    kind: String,
    payload: Map<String, Value>,
    source_event_ids: Vec<String>,
    occurred_at: String,
    event_hash: String,
}

#[derive(Clone, Serialize)]
struct BridgeEmission {
    source: &'static str,
    event: ExperienceEvent,
}

#[derive(Clone, Serialize)]
struct BridgeRejection {
    source: &'static str,
    line_number: u64,
    reason: String,
}

#[derive(Serialize)]
struct BridgeStatus {
    schema: &'static str,
    wire_schema: &'static str,
    contract_sha256: &'static str,
    mode: &'static str,
    stream_path: Option<String>,
    configuration_error: Option<String>,
    network_enabled: bool,
    shell_enabled: bool,
}

#[derive(Default)]
struct StreamValidator {
    seen: HashSet<String>,
    turns: HashMap<String, TurnState>,
    jobs: HashMap<String, JobState>,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum TurnState { Streaming, Terminal }

#[derive(Clone, Copy, Eq, PartialEq)]
enum JobState { Active, Terminal }

struct BridgeState {
    stream_path: Option<PathBuf>,
    configuration_error: Option<String>,
    started: Mutex<bool>,
    validator: Arc<Mutex<StreamValidator>>,
}

#[tauri::command]
fn bridge_status(state: State<'_, BridgeState>) -> BridgeStatus {
    let started = state.started.lock().map(|value| *value).unwrap_or(false);
    BridgeStatus {
        schema: CONTRACT_SCHEMA,
        wire_schema: WIRE_SCHEMA,
        contract_sha256: CONTRACT_SHA256,
        mode: if state.configuration_error.is_some() { "CONFIGURATION_REJECTED" } else if started { "RUNTIME_VALIDATED" } else if state.stream_path.is_some() { "RUNTIME_CONFIGURED" } else { "WAITING_FOR_RUNTIME_STREAM" },
        stream_path: state.stream_path.as_ref().map(|path| path.display().to_string()),
        configuration_error: state.configuration_error.clone(),
        network_enabled: false,
        shell_enabled: false,
    }
}

#[tauri::command]
fn start_bridge(app: tauri::AppHandle, state: State<'_, BridgeState>) -> Result<BridgeStatus, String> {
    if state.configuration_error.is_some() { return Ok(bridge_status(state)); }
    if let Some(path) = &state.stream_path {
        let mut started = state.started.lock().map_err(|_| "estado do bridge indisponível")?;
        if !*started {
            follow_stream(app, path.clone(), Arc::clone(&state.validator));
            *started = true;
        }
    }
    Ok(bridge_status(state))
}

impl StreamValidator {
    fn accept(&mut self, event: &ExperienceEvent) -> Result<(), String> {
        if !self.seen.insert(event.event_id.clone()) { return Err("evento UX duplicado".into()); }
        let result = self.accept_lifecycle(event);
        if result.is_err() { self.seen.remove(&event.event_id); }
        result
    }

    fn accept_lifecycle(&mut self, event: &ExperienceEvent) -> Result<(), String> {
        match event.kind.as_str() {
            "ASSISTANT_START" => {
                let turn = string_field(&event.payload, "turn_id")?;
                if self.turns.contains_key(turn) { return Err("turno assistente duplicado".into()); }
                self.turns.insert(turn.into(), TurnState::Streaming);
            }
            "ASSISTANT_TOKEN" => {
                let turn = string_field(&event.payload, "turn_id")?;
                if self.turns.get(turn) != Some(&TurnState::Streaming) { return Err("token fora de turno ativo".into()); }
                let expected = self.turn_token_count(turn) + 1;
                let actual = event.payload.get("sequence").and_then(Value::as_u64).ok_or("sequência de token inválida")?;
                if actual != expected { return Err("token fora de ordem".into()); }
                self.turns.insert(format!("{turn}#{actual}"), TurnState::Terminal);
            }
            "ASSISTANT_END" => {
                let turn = string_field(&event.payload, "turn_id")?;
                if self.turns.get(turn) != Some(&TurnState::Streaming) { return Err("fim de turno sem stream ativo".into()); }
                self.turns.insert(turn.into(), TurnState::Terminal);
            }
            "JOB_STARTED" => {
                let job = string_field(&event.payload, "job_id")?;
                if self.jobs.contains_key(job) { return Err("job UX duplicado".into()); }
                self.jobs.insert(job.into(), JobState::Active);
            }
            "JOB_MILESTONE" => { self.require_active_job(event)?; }
            "JOB_COMPLETED" | "JOB_FAILED" | "JOB_CANCELLED" => {
                let job = self.require_active_job(event)?.to_owned();
                self.jobs.insert(job, JobState::Terminal);
            }
            _ => {}
        }
        Ok(())
    }

    fn turn_token_count(&self, turn: &str) -> u64 {
        self.turns.keys().filter_map(|key| key.strip_prefix(&format!("{turn}#"))).filter_map(|value| value.parse::<u64>().ok()).max().unwrap_or(0)
    }

    fn require_active_job<'a>(&self, event: &'a ExperienceEvent) -> Result<&'a str, String> {
        let job = string_field(&event.payload, "job_id")?;
        if self.jobs.get(job) != Some(&JobState::Active) { return Err("evento de job sem STARTED ativo".into()); }
        Ok(job)
    }
}

fn validate_event_line(line: &str, validator: &mut StreamValidator) -> Result<Option<ExperienceEvent>, String> {
    if line.as_bytes().len() > MAX_EVENT_BYTES { return Err("evento UX excede limite".into()); }
    let Some(json) = line.trim_end_matches(['\r', '\n']).strip_prefix(EVENT_PREFIX) else { return Ok(None); };
    let event: ExperienceEvent = serde_json::from_str(json).map_err(|_| "evento UX não é JSON válido")?;
    validate_event_shape(&event)?;
    validate_event_hash(&event)?;
    validator.accept(&event)?;
    Ok(Some(event))
}

fn validate_event_shape(event: &ExperienceEvent) -> Result<(), String> {
    const KINDS: [&str; 14] = ["PRESENCE_READY", "MODEL_LOADING", "MODEL_READY", "INPUT_REQUEST", "ASSISTANT_START", "ASSISTANT_TOKEN", "ASSISTANT_END", "JOB_STARTED", "JOB_MILESTONE", "JOB_COMPLETED", "JOB_FAILED", "JOB_CANCELLED", "NOTICE", "RECOVERABLE_ERROR"];
    if event.schema != WIRE_SCHEMA || event.event_id.is_empty() || event.occurred_at.is_empty() || event.source_event_ids.is_empty() || event.source_event_ids.iter().any(String::is_empty) { return Err("evento UX incompleto ou incompatível".into()); }
    if !KINDS.contains(&event.kind.as_str()) { return Err("kind UX inválido".into()); }
    for key in ["progress_percent", "percentage", "eta", "fake_progress"] { if event.payload.contains_key(key) { return Err("progresso fabricado é proibido".into()); } }
    if matches!(event.kind.as_str(), "ASSISTANT_START" | "ASSISTANT_TOKEN" | "ASSISTANT_END") { string_field(&event.payload, "turn_id")?; }
    if event.kind == "ASSISTANT_TOKEN" {
        let text = string_field(&event.payload, "text")?;
        if text.is_empty() || text.len() > 8192 || event.payload.get("sequence").and_then(Value::as_u64).unwrap_or(0) == 0 { return Err("token UX inválido".into()); }
    }
    if event.kind.starts_with("JOB_") {
        string_field(&event.payload, "job_id")?;
        let summary = string_field(&event.payload, "summary")?;
        let evidence = string_field(&event.payload, "evidence_sha256")?;
        if summary.trim().is_empty() || !is_sha256(evidence) { return Err("job exige evidência SHA-256 e resumo".into()); }
    }
    Ok(())
}

fn validate_event_hash(event: &ExperienceEvent) -> Result<(), String> {
    if !is_sha256(&event.event_hash) { return Err("hash UX inválido".into()); }
    let unsigned = serde_json::json!({
        "schema": event.schema,
        "event_id": event.event_id,
        "kind": event.kind,
        "payload": event.payload,
        "source_event_ids": event.source_event_ids,
        "occurred_at": event.occurred_at,
    });
    let canonical = canonical_json(&unsigned);
    let digest = Sha256::digest(format!("{canonical}\n").as_bytes());
    let actual = digest.iter().map(|byte| format!("{byte:02x}")).collect::<String>();
    if actual != event.event_hash {
        return Err("evento UX adulterado".into());
    }
    Ok(())
}

fn canonical_json(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let mut keys = map.keys().collect::<Vec<_>>(); keys.sort();
            let body = keys.into_iter().map(|key| format!("{}:{}", serde_json::to_string(key).expect("key"), canonical_json(&map[key]))).collect::<Vec<_>>().join(",");
            format!("{{{body}}}")
        }
        Value::Array(items) => format!("[{}]", items.iter().map(canonical_json).collect::<Vec<_>>().join(",")),
        _ => serde_json::to_string(value).expect("scalar"),
    }
}

fn string_field<'a>(payload: &'a Map<String, Value>, name: &str) -> Result<&'a str, String> {
    payload.get(name).and_then(Value::as_str).filter(|value| !value.is_empty()).ok_or_else(|| format!("campo {name} ausente"))
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        && value.bytes().any(|byte| byte != b'0')
}

fn configured_stream_path() -> Result<Option<PathBuf>, String> {
    let Some(raw) = std::env::var_os("CASULO_UX_EVENT_STREAM") else { return Ok(None); };
    validate_stream_path(Path::new(&raw)).map(Some)
}

fn validate_stream_path(path: &Path) -> Result<PathBuf, String> {
    if !path.is_absolute() || path.extension().and_then(|value| value.to_str()) != Some("jsonl") { return Err("stream precisa ser JSONL absoluto".into()); }
    let local = std::env::var_os("LOCALAPPDATA").ok_or("LOCALAPPDATA indisponível")?;
    let allowed = Path::new(&local).join("Casulo").join("experience");
    fs::create_dir_all(&allowed).map_err(|_| "diretório local do Casulo indisponível")?;
    let allowed = fs::canonicalize(&allowed).map_err(|_| "raiz local do Casulo inválida")?;
    let canonical = fs::canonicalize(path).map_err(|_| "stream configurado não existe")?;
    if !canonical.starts_with(&allowed) || !canonical.is_file() { return Err("stream fora da raiz confinada".into()); }
    Ok(canonical)
}

fn follow_stream(app: tauri::AppHandle, path: PathBuf, validator: Arc<Mutex<StreamValidator>>) {
    thread::spawn(move || {
        let Ok(file) = File::open(path) else { return; };
        let mut reader = BufReader::new(file);
        let mut line = String::new();
        let mut line_number = 0_u64;
        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) => thread::sleep(Duration::from_millis(50)),
                Ok(_) => {
                    line_number += 1;
                    let outcome = validator.lock().map_err(|_| "validator indisponível".to_string()).and_then(|mut guard| validate_event_line(&line, &mut guard));
                    match outcome {
                        Ok(Some(event)) => { let _ = app.emit(EVENT_CHANNEL, BridgeEmission { source: "RUNTIME_VALIDATED", event }); }
                        Ok(None) => {}
                        Err(reason) => { let _ = app.emit(REJECTION_CHANNEL, BridgeRejection { source: "RUNTIME_REJECTED", line_number, reason }); }
                    }
                }
                Err(_) => { let _ = app.emit(REJECTION_CHANNEL, BridgeRejection { source: "RUNTIME_REJECTED", line_number, reason: "falha de leitura do stream".into() }); break; }
            }
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let (stream_path, configuration_error) = match configured_stream_path() {
        Ok(path) => (path, None),
        Err(error) => (None, Some(error)),
    };
    let validator = Arc::new(Mutex::new(StreamValidator::default()));
    let state = BridgeState { stream_path, configuration_error, started: Mutex::new(false), validator };
    tauri::Builder::default()
        .manage(state)
        .invoke_handler(tauri::generate_handler![bridge_status, start_bridge])
        .run(tauri::generate_context!())
        .expect("Casulo owner UI failed to start");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn event_line(event_id: &str, kind: &str, payload: Value) -> String {
        let unsigned = serde_json::json!({
            "schema": WIRE_SCHEMA,
            "event_id": event_id,
            "kind": kind,
            "payload": payload,
            "source_event_ids": ["runtime:test"],
            "occurred_at": "2026-08-20T12:00:00-03:00",
        });
        let hash = Sha256::digest(format!("{}\n", canonical_json(&unsigned)).as_bytes()).iter().map(|byte| format!("{byte:02x}")).collect::<String>();
        let mut object = unsigned.as_object().unwrap().clone();
        object.insert("event_hash".into(), Value::String(hash));
        format!("{EVENT_PREFIX}{}\n", canonical_json(&Value::Object(object)))
    }

    #[test]
    fn validates_python_compatible_hash_and_stream_order() {
        let mut validator = StreamValidator::default();
        let start = event_line("ux:1", "ASSISTANT_START", serde_json::json!({"turn_id":"turn:1"}));
        let token = event_line("ux:2", "ASSISTANT_TOKEN", serde_json::json!({"turn_id":"turn:1","sequence":1,"text":"Olá"}));
        let end = event_line("ux:3", "ASSISTANT_END", serde_json::json!({"turn_id":"turn:1"}));
        assert!(validate_event_line(&start, &mut validator).unwrap().is_some());
        assert!(validate_event_line(&token, &mut validator).unwrap().is_some());
        assert!(validate_event_line(&end, &mut validator).unwrap().is_some());
    }

    #[test]
    fn accepts_an_event_encoded_by_the_existing_python_runtime() {
        let mut validator = StreamValidator::default();
        let line = include_str!("../tests/python-event.jsonl");
        let event = validate_event_line(line, &mut validator).unwrap().unwrap();
        assert_eq!(event.event_id, "ux:cross-language:1");
        assert_eq!(event.kind, "JOB_STARTED");
        assert_eq!(event.event_hash, "767f9507574e15aa08810d6bd90cb931de445134641d80ed831f557d52d046aa");
    }

    #[test]
    fn rejects_tampering_fake_progress_and_late_job_completion() {
        let mut validator = StreamValidator::default();
        let mut tampered = event_line("ux:1", "NOTICE", serde_json::json!({"text":"ok"}));
        tampered = tampered.replace("\"ok\"", "\"não\"");
        assert!(validate_event_line(&tampered, &mut validator).unwrap_err().contains("adulterado"));
        let fake = event_line("ux:2", "NOTICE", serde_json::json!({"text":"x","eta":"1s"}));
        assert!(validate_event_line(&fake, &mut validator).unwrap_err().contains("fabricado"));
        let evidence = "a".repeat(64);
        let started = event_line("ux:3", "JOB_STARTED", serde_json::json!({"job_id":"job:1","summary":"start","evidence_sha256":evidence}));
        let cancelled = event_line("ux:4", "JOB_CANCELLED", serde_json::json!({"job_id":"job:1","summary":"stop","evidence_sha256":"b".repeat(64)}));
        let completed = event_line("ux:5", "JOB_COMPLETED", serde_json::json!({"job_id":"job:1","summary":"late","evidence_sha256":"c".repeat(64)}));
        validate_event_line(&started, &mut validator).unwrap();
        validate_event_line(&cancelled, &mut validator).unwrap();
        assert!(validate_event_line(&completed, &mut validator).unwrap_err().contains("sem STARTED"));
    }

    #[test]
    fn rejects_zero_digest_as_job_evidence() {
        let mut validator = StreamValidator::default();
        let zero = event_line(
            "ux:zero",
            "JOB_STARTED",
            serde_json::json!({"job_id":"job:zero","summary":"sem prova","evidence_sha256":"0".repeat(64)}),
        );
        assert!(validate_event_line(&zero, &mut validator)
            .unwrap_err()
            .contains("evidência"));
    }

    #[test]
    fn ignores_incidental_stdout_and_rejects_oversized_input() {
        let mut validator = StreamValidator::default();
        assert!(validate_event_line("normal process output\n", &mut validator).unwrap().is_none());
        assert!(validate_event_line(&format!("{EVENT_PREFIX}{}", "x".repeat(MAX_EVENT_BYTES)), &mut validator).unwrap_err().contains("excede"));
    }

    #[test]
    fn rejects_relative_stream_paths_before_touching_the_filesystem() {
        assert!(validate_stream_path(Path::new("events.jsonl")).unwrap_err().contains("absoluto"));
    }
}
