//! TCAP v2 verifier and bounded T/2.0 interpreter used by the Native
//! conformance image. The ramdisk is self-contained: no host path, network or
//! block device is reachable from this module.

use alloc::collections::BTreeMap;
use alloc::format;
use alloc::string::{String, ToString};
use alloc::vec::Vec;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

const MAX_BUNDLE_BYTES: usize = 16 * 1024 * 1024;
const ZERO_HASH: &str = "0000000000000000000000000000000000000000000000000000000000000000";
const REQUIRED_SECTIONS: [&str; 14] = [
    "header",
    "module_graph",
    "typed_ir",
    "functional_code",
    "readonly_data",
    "effects",
    "capabilities",
    "resource_budgets",
    "schemas",
    "source_map",
    "tests",
    "foreign_boundaries",
    "provenance",
    "signature_class",
];

pub struct NativeProbe {
    pub tcap_hash: String,
    pub input_payload: Value,
    pub result: Value,
    pub observable: String,
    pub receipt: String,
    pub receipt_hash: String,
    pub steps: u64,
}

pub fn is_native_probe(raw: &[u8]) -> bool {
    raw.first() == Some(&b'{')
        && raw
            .windows(b"casulo.native-t-v2-probe/1.0".len())
            .any(|window| window == b"casulo.native-t-v2-probe/1.0")
}

fn sha(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn canonical(value: &Value) -> Result<Vec<u8>, String> {
    serde_json::to_vec(value).map_err(|_| "CANONICAL_JSON".to_string())
}

fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("MISSING_TEXT:{key}"))
}

fn array<'a>(value: &'a Value, key: &str) -> Result<&'a Vec<Value>, String> {
    value
        .get(key)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("MISSING_ARRAY:{key}"))
}

fn parse_embedded(entry: &Value) -> Result<Value, String> {
    let content = text(entry, "content_utf8")?;
    if sha(content.as_bytes()) != text(entry, "sha256")? {
        return Err("EMBEDDED_HASH".to_string());
    }
    serde_json::from_str(content).map_err(|_| "EMBEDDED_JSON".to_string())
}

pub fn execute(raw: &[u8]) -> Result<NativeProbe, String> {
    execute_inner(raw, None, None)
}

/// Execute an already verified T/2.0 program against runtime evidence.
///
/// The bundle remains the content-addressed executable and is fully verified
/// before this override is consumed. Only the request payload and receipt-chain
/// predecessor are supplied at runtime; neither may change the program, IR,
/// capabilities, grants, budgets, or provenance sealed in the bundle.
pub fn execute_with_payload(
    raw: &[u8],
    runtime_payload: &Value,
    previous_receipt_hash: Option<&str>,
) -> Result<NativeProbe, String> {
    execute_inner(raw, Some(runtime_payload), previous_receipt_hash)
}

fn execute_inner(
    raw: &[u8],
    runtime_payload: Option<&Value>,
    previous_receipt_hash: Option<&str>,
) -> Result<NativeProbe, String> {
    if raw.is_empty() || raw.len() > MAX_BUNDLE_BYTES {
        return Err("BUNDLE_SIZE".to_string());
    }
    let bundle: Value = serde_json::from_slice(raw).map_err(|_| "BUNDLE_JSON".to_string())?;
    if text(&bundle, "schema")? != "casulo.native-t-v2-probe/1.0" {
        return Err("BUNDLE_SCHEMA".to_string());
    }
    let bundle_hash = text(&bundle, "bundle_sha256")?;
    let mut bundle_seed = bundle.as_object().cloned().ok_or("BUNDLE_OBJECT")?;
    bundle_seed.remove("bundle_sha256");
    if sha(&canonical(&Value::Object(bundle_seed))?) != bundle_hash {
        return Err("BUNDLE_IDENTITY".to_string());
    }

    let manifest = bundle.get("manifest").ok_or("MANIFEST")?;
    if text(manifest, "schema")? != "casulo.tcap/2.0" {
        return Err("TCAP_SCHEMA".to_string());
    }
    let manifest_sections = manifest
        .get("sections")
        .and_then(Value::as_object)
        .ok_or("MANIFEST_SECTIONS")?;
    let embedded_sections = bundle
        .get("sections")
        .and_then(Value::as_object)
        .ok_or("BUNDLE_SECTIONS")?;
    if manifest_sections.len() != REQUIRED_SECTIONS.len()
        || embedded_sections.len() != REQUIRED_SECTIONS.len()
        || REQUIRED_SECTIONS.iter().any(|name| {
            !manifest_sections.contains_key(*name) || !embedded_sections.contains_key(*name)
        })
    {
        return Err("SECTION_SET".to_string());
    }
    let mut sections = BTreeMap::new();
    for name in REQUIRED_SECTIONS {
        let manifest_entry = &manifest_sections[name];
        let embedded = &embedded_sections[name];
        if text(manifest_entry, "file")? != text(embedded, "file")?
            || text(manifest_entry, "sha256")? != text(embedded, "sha256")?
        {
            return Err("SECTION_DESCRIPTOR".to_string());
        }
        sections.insert(name, parse_embedded(embedded)?);
    }
    if sections["header"]
        != json!({"schema":"casulo.tcap/2.0","target":"portable-t-vm","verified_before_execution":true})
    {
        return Err("HEADER_CONTRACT".to_string());
    }

    let manifest_sources = array(manifest, "sources")?;
    let embedded_sources = array(&bundle, "sources")?;
    if manifest_sources.len() != embedded_sources.len() || manifest_sources.is_empty() {
        return Err("SOURCE_SET".to_string());
    }
    for (descriptor, embedded) in manifest_sources.iter().zip(embedded_sources) {
        for key in ["module", "file", "sha256"] {
            if text(descriptor, key)? != text(embedded, key)? {
                return Err("SOURCE_DESCRIPTOR".to_string());
            }
        }
        let content = text(embedded, "content_utf8")?;
        if sha(content.as_bytes()) != text(descriptor, "sha256")? {
            return Err("SOURCE_HASH".to_string());
        }
    }
    let tcap_seed = json!({
        "schema": "casulo.tcap/2.0",
        "sections": manifest.get("sections").ok_or("SECTIONS")?,
        "sources": manifest_sources,
    });
    let tcap_hash = sha(&canonical(&tcap_seed)?);
    if tcap_hash != text(manifest, "tcap_hash")? {
        return Err("TCAP_IDENTITY".to_string());
    }

    let typed = &sections["typed_ir"];
    let code = &sections["functional_code"];
    if text(typed, "schema")? != "casulo.t-ir-bundle/2.0"
        || text(code, "schema")? != "casulo.t-bytecode/2.0"
        || text(code, "encoding")? != "structured-opcodes"
        || code.get("entry") != manifest.get("entry")
    {
        return Err("BYTECODE_CONTRACT".to_string());
    }
    let entry = manifest.get("entry").ok_or("ENTRY")?;
    let module_name = text(entry, "module")?;
    let request = bundle.get("request").ok_or("REQUEST")?;
    let function_name = text(request, "function")?;
    let module = array(typed, "modules")?
        .iter()
        .find(|item| item.get("module").and_then(Value::as_str) == Some(module_name))
        .ok_or("MODULE_NOT_FOUND")?;
    let function = array(module, "functions")?
        .iter()
        .find(|item| item.get("name").and_then(Value::as_str) == Some(function_name))
        .ok_or("FUNCTION_NOT_FOUND")?;
    let code_module = array(code, "modules")?
        .iter()
        .find(|item| item.get("name").and_then(Value::as_str) == Some(module_name))
        .ok_or("CODE_MODULE_NOT_FOUND")?;
    let code_function = array(code_module, "functions")?
        .iter()
        .find(|item| item.get("name").and_then(Value::as_str) == Some(function_name))
        .ok_or("CODE_FUNCTION_NOT_FOUND")?;
    if code_function != function {
        return Err("CODE_IR_DIVERGENCE".to_string());
    }

    let payload = match runtime_payload {
        Some(value) => value.as_object().cloned().ok_or("RUNTIME_PAYLOAD_OBJECT")?,
        None => request
            .get("payload")
            .and_then(Value::as_object)
            .cloned()
            .ok_or("PAYLOAD_OBJECT")?,
    };
    let grants = array(request, "grants")?
        .iter()
        .map(|item| item.as_str().ok_or("GRANT_TYPE").map(ToString::to_string))
        .collect::<Result<Vec<_>, _>>()?;
    let capabilities = array(module, "capabilities")?
        .iter()
        .map(|item| {
            item.as_str()
                .ok_or("CAPABILITY_TYPE")
                .map(ToString::to_string)
        })
        .collect::<Result<Vec<_>, _>>()?;
    let declared_effects = array(function, "effects")?
        .iter()
        .map(|item| item.as_str().ok_or("EFFECT_TYPE").map(ToString::to_string))
        .collect::<Result<Vec<_>, _>>()?;
    verify_block(array(function, "code")?, &declared_effects, &capabilities)?;
    let mut state = Map::new();
    for item in array(module, "states")? {
        state.insert(
            text(item, "name")?.to_string(),
            item.get("initial").cloned().ok_or("STATE_INITIAL")?,
        );
    }
    let initial = state.clone();
    let mut environment = BTreeMap::new();
    environment.insert(
        text(function.get("parameter").ok_or("PARAMETER")?, "name")?.to_string(),
        Value::Object(payload.clone()),
    );
    environment.insert("state".to_string(), Value::Object(state.clone()));
    let max_steps = module
        .get("budgets")
        .and_then(|item| item.get("steps"))
        .and_then(Value::as_u64)
        .ok_or("STEP_BUDGET")?;
    let mut machine = Machine {
        state,
        initial,
        environment,
        grants,
        capabilities,
        declared_effects,
        effects: Vec::new(),
        events: Vec::new(),
        jobs: BTreeMap::new(),
        diagnostics: Vec::new(),
        steps: 0,
        max_steps,
    };
    let result = machine
        .block(array(function, "code")?)?
        .ok_or("MISSING_RETURN")?;
    let mut state_delta = Map::new();
    for (key, value) in &machine.state {
        if machine.initial.get(key) != Some(value) {
            state_delta.insert(key.clone(), value.clone());
        }
    }
    let observable = json!({
        "result": result.clone(),
        "state_delta": state_delta,
        "requested_effects": machine.effects,
        "events": machine.events,
        "jobs": machine.jobs.values().cloned().collect::<Vec<_>>(),
        "diagnostics": machine.diagnostics,
    });
    let output_hash = sha(&canonical(&observable)?);
    let input_hash = sha(&canonical(&Value::Object(payload.clone()))?);
    let source_hash = manifest_sources
        .iter()
        .find(|item| item.get("module").and_then(Value::as_str) == Some(module_name))
        .and_then(|item| item.get("sha256"))
        .and_then(Value::as_str)
        .ok_or("ENTRY_SOURCE")?;
    let ir_hash = sha(&canonical(module)?);
    let previous = previous_receipt_hash.unwrap_or_else(|| {
        request
            .get("previous_receipt_hash")
            .and_then(Value::as_str)
            .unwrap_or(ZERO_HASH)
    });
    if previous.len() != 64 || previous.bytes().any(|byte| !byte.is_ascii_hexdigit()) {
        return Err("PREVIOUS_RECEIPT_HASH".to_string());
    }
    let grants_consumed = observable["requested_effects"]
        .as_array()
        .ok_or("OBS_EFFECTS")?
        .iter()
        .filter(|effect| {
            machine
                .grants
                .iter()
                .any(|grant| effect.as_str() == Some(grant))
        })
        .cloned()
        .collect::<Vec<_>>();
    let receipt_seed = json!({
        "schema": "casulo.t-decision-receipt/2.0",
        "decision_id": format!("decision:{}", &output_hash[..24]),
        "surface_id": text(request, "surface_id")?,
        "scope_id": text(request, "scope_id")?,
        "t_source_hash": source_hash,
        "t_ir_hash": ir_hash,
        "tcap_hash": tcap_hash,
        "runtime_function": format!("{module_name}::{function_name}"),
        "canonical_input_hash": input_hash,
        "canonical_output_hash": output_hash,
        "effects_requested": observable["requested_effects"],
        "grants_consumed": grants_consumed,
        "foreign_calls": [],
        "result": observable["result"]["kind"],
        "previous_receipt_hash": previous,
        "monotonic_timestamp_ns": crate::interrupts::timer_ticks(),
        "runtime_id": "t-runtime/native-2.0",
    });
    let mut receipt = receipt_seed.as_object().cloned().ok_or("RECEIPT")?;
    let receipt_hash = sha(&canonical(&receipt_seed)?);
    receipt.insert("receipt_hash".to_string(), json!(receipt_hash.clone()));
    Ok(NativeProbe {
        tcap_hash,
        input_payload: Value::Object(payload),
        result,
        observable: serde_json::to_string(&observable).map_err(|_| "OBSERVABLE_JSON")?,
        receipt: serde_json::to_string(&Value::Object(receipt)).map_err(|_| "RECEIPT_JSON")?,
        receipt_hash,
        steps: machine.steps,
    })
}

struct Machine {
    state: Map<String, Value>,
    initial: Map<String, Value>,
    environment: BTreeMap<String, Value>,
    grants: Vec<String>,
    capabilities: Vec<String>,
    declared_effects: Vec<String>,
    effects: Vec<String>,
    events: Vec<Value>,
    jobs: BTreeMap<String, Value>,
    diagnostics: Vec<String>,
    steps: u64,
    max_steps: u64,
}

impl Machine {
    fn tick(&mut self) -> Result<(), String> {
        self.steps = self.steps.checked_add(1).ok_or("STEP_OVERFLOW")?;
        if self.steps > self.max_steps {
            Err("RESOURCE_STEPS_EXHAUSTED".to_string())
        } else {
            Ok(())
        }
    }

    fn eval(&mut self, node: &Value) -> Result<Value, String> {
        self.tick()?;
        let op = text(node, "op")?;
        match op {
            "const" => node.get("value").cloned().ok_or("CONST_VALUE".to_string()),
            "name" => self
                .environment
                .get(text(node, "name")?)
                .cloned()
                .ok_or("NAME_NOT_FOUND".to_string()),
            "path" => {
                let mut value = self
                    .environment
                    .get(text(node, "root")?)
                    .cloned()
                    .ok_or("ROOT_NOT_FOUND")?;
                for part in array(node, "path")? {
                    value = value
                        .get(part.as_str().ok_or("PATH_ITEM")?)
                        .cloned()
                        .ok_or("FIELD_NOT_FOUND")?;
                }
                Ok(value)
            }
            "not" => Ok(Value::Bool(
                !self
                    .eval(node.get("value").ok_or("NOT_VALUE")?)?
                    .as_bool()
                    .ok_or("BOOL_EXPECTED")?,
            )),
            "and" | "or" => {
                let mut values = Vec::new();
                for item in array(node, "values")? {
                    values.push(self.eval(item)?.as_bool().ok_or("BOOL_EXPECTED")?);
                }
                Ok(Value::Bool(if op == "and" {
                    values.iter().all(|value| *value)
                } else {
                    values.iter().any(|value| *value)
                }))
            }
            "eq" | "ne" | "lt" | "le" | "gt" | "ge" => {
                let left = self.eval(node.get("left").ok_or("LEFT")?)?;
                let right = self.eval(node.get("right").ok_or("RIGHT")?)?;
                let result = match op {
                    "eq" => left == right,
                    "ne" => left != right,
                    "lt" => number(&left)? < number(&right)?,
                    "le" => number(&left)? <= number(&right)?,
                    "gt" => number(&left)? > number(&right)?,
                    "ge" => number(&left)? >= number(&right)?,
                    _ => false,
                };
                Ok(Value::Bool(result))
            }
            "list" => {
                let mut out = Vec::new();
                for item in array(node, "items")? {
                    out.push(self.eval(item)?);
                }
                Ok(Value::Array(out))
            }
            "map" => {
                let mut out = Map::new();
                for item in array(node, "items")? {
                    let pair = item.as_array().ok_or("MAP_PAIR")?;
                    let key = self.eval(&pair[0])?.as_str().ok_or("MAP_KEY")?.to_string();
                    out.insert(key, self.eval(&pair[1])?);
                }
                Ok(Value::Object(out))
            }
            "call" => {
                let mut args = Vec::new();
                for item in array(node, "args")? {
                    args.push(self.eval(item)?);
                }
                match text(node, "name")? {
                    "len" => Ok(json!(
                        args[0]
                            .as_array()
                            .map(Vec::len)
                            .or_else(|| args[0].as_object().map(Map::len))
                            .or_else(|| args[0].as_str().map(str::len))
                            .ok_or("LEN_TYPE")?
                    )),
                    "all_equal" => Ok(Value::Bool(
                        args[0]
                            .as_array()
                            .ok_or("ALL_EQUAL_LIST")?
                            .iter()
                            .all(|value| value == &args[1]),
                    )),
                    "contains" => Ok(Value::Bool(
                        args[0]
                            .as_array()
                            .map(|items| items.contains(&args[1]))
                            .or_else(|| {
                                args[0].as_str().and_then(|haystack| {
                                    args[1].as_str().map(|needle| haystack.contains(needle))
                                })
                            })
                            .ok_or("CONTAINS_TYPE")?,
                    )),
                    "add" => {
                        if let (Some(left), Some(right)) = (args[0].as_i64(), args[1].as_i64()) {
                            Ok(json!(left.checked_add(right).ok_or("INTEGER_OVERFLOW")?))
                        } else {
                            Ok(json!(number(&args[0])? + number(&args[1])?))
                        }
                    }
                    "get" => {
                        let key = args[1].as_str().ok_or("GET_KEY")?;
                        Ok(args[0]
                            .get(key)
                            .cloned()
                            .unwrap_or_else(|| args.get(2).cloned().unwrap_or(Value::Null)))
                    }
                    _ => Err("CALL_NOT_ALLOWED".to_string()),
                }
            }
            _ => Err(format!("UNKNOWN_EXPRESSION:{op}")),
        }
    }

    fn block(&mut self, code: &[Value]) -> Result<Option<Value>, String> {
        for instruction in code {
            self.tick()?;
            let op = text(instruction, "op")?;
            match op {
                "require" | "ensure" => {
                    if !self
                        .eval(instruction.get("condition").ok_or("CONDITION")?)?
                        .as_bool()
                        .ok_or("BOOL_EXPECTED")?
                    {
                        return Ok(Some(
                            json!({"kind":"error","value":instruction.get("error").cloned().ok_or("ERROR_VALUE")?}),
                        ));
                    }
                }
                "cancel_if" => {
                    if self
                        .eval(instruction.get("value").ok_or("CANCEL_VALUE")?)?
                        .as_bool()
                        .ok_or("BOOL_EXPECTED")?
                    {
                        return Ok(Some(json!({"kind":"error","value":"CANCELLED"})));
                    }
                }
                "let" => {
                    let value = self.eval(instruction.get("value").ok_or("LET_VALUE")?)?;
                    self.environment
                        .insert(text(instruction, "name")?.to_string(), value);
                }
                "set_state" => {
                    let name = text(instruction, "name")?.to_string();
                    let value = self.eval(instruction.get("value").ok_or("STATE_VALUE")?)?;
                    self.state.insert(name, value);
                    self.environment
                        .insert("state".to_string(), Value::Object(self.state.clone()));
                }
                "request_effect" => {
                    let effect = text(instruction, "effect")?.to_string();
                    if !self.declared_effects.contains(&effect)
                        || !self.capabilities.contains(&effect)
                    {
                        return Err("UNDECLARED_EFFECT".to_string());
                    }
                    if !self.grants.contains(&effect) {
                        return Ok(Some(
                            json!({"kind":"error","value":format!("CAPABILITY_DENIED:{effect}")}),
                        ));
                    }
                    self.effects.push(effect);
                }
                "emit_event" => {
                    let value = self.eval(instruction.get("value").ok_or("EVENT_VALUE")?)?;
                    self.events.push(value);
                }
                "return_ok" => {
                    return Ok(Some(
                        json!({"kind":"ok","value":self.eval(instruction.get("value").ok_or("RETURN_VALUE")?)?}),
                    ));
                }
                "return_error" => {
                    return Ok(Some(
                        json!({"kind":"error","value":self.eval(instruction.get("value").ok_or("RETURN_VALUE")?)?}),
                    ));
                }
                "if" => {
                    let chosen = if self
                        .eval(instruction.get("condition").ok_or("IF_CONDITION")?)?
                        .as_bool()
                        .ok_or("BOOL_EXPECTED")?
                    {
                        array(instruction, "then")?
                    } else {
                        array(instruction, "else")?
                    };
                    if let Some(value) = self.block(chosen)? {
                        return Ok(Some(value));
                    }
                }
                "for" => {
                    let values = self.eval(instruction.get("iterable").ok_or("ITERABLE")?)?;
                    let items = values.as_array().ok_or("FOR_EXPECTED_LIST")?;
                    let limit = instruction
                        .get("limit")
                        .and_then(Value::as_u64)
                        .ok_or("LOOP_LIMIT")? as usize;
                    if items.len() > limit {
                        return Ok(Some(
                            json!({"kind":"error","value":"COLLECTION_BOUND_EXCEEDED"}),
                        ));
                    }
                    for value in items {
                        let name = text(instruction, "name")?.to_string();
                        let old = self.environment.insert(name.clone(), value.clone());
                        if let Some(result) = self.block(array(instruction, "body")?)? {
                            return Ok(Some(result));
                        }
                        if let Some(previous) = old {
                            self.environment.insert(name, previous);
                        } else {
                            self.environment.remove(&name);
                        }
                    }
                }
                "spawn_job" => {
                    let name = text(instruction, "name")?.to_string();
                    if self.jobs.contains_key(&name) {
                        return Ok(Some(json!({"kind":"error","value":"JOB_ALREADY_EXISTS"})));
                    }
                    let payload = self.eval(instruction.get("payload").ok_or("JOB_PAYLOAD")?)?;
                    let job = json!({"name":name,"status":"spawned","payload":payload,"limit":instruction.get("limit").ok_or("JOB_LIMIT")?});
                    self.jobs.insert(name.clone(), job.clone());
                    self.environment.insert(name, job);
                }
                "join_job" => {
                    let name = text(instruction, "name")?.to_string();
                    let job = self.jobs.get_mut(&name).ok_or("JOB_NOT_FOUND")?;
                    job["status"] = json!("joined");
                }
                "match" => {
                    let value = self.eval(instruction.get("value").ok_or("MATCH_VALUE")?)?;
                    let label = if let Some(boolean) = value.as_bool() {
                        boolean.to_string()
                    } else if let Some(text) = value.as_str() {
                        text.to_string()
                    } else {
                        value.to_string()
                    };
                    let cases = array(instruction, "cases")?;
                    let case = cases
                        .iter()
                        .find(|item| item.get("label").and_then(Value::as_str) == Some(&label))
                        .or_else(|| {
                            cases
                                .iter()
                                .find(|item| item.get("label").and_then(Value::as_str) == Some("_"))
                        })
                        .ok_or("NON_EXHAUSTIVE_MATCH")?;
                    if let Some(result) = self.block(array(case, "body")?)? {
                        return Ok(Some(result));
                    }
                }
                _ => return Err(format!("UNKNOWN_OPCODE:{op}")),
            }
        }
        Ok(None)
    }
}

fn number(value: &Value) -> Result<f64, String> {
    value.as_f64().ok_or("NUMBER_EXPECTED".to_string())
}

fn verify_expression(node: &Value) -> Result<(), String> {
    match text(node, "op")? {
        "const" => {
            if node.get("value").is_none() {
                return Err("CONST_VALUE".to_string());
            }
        }
        "name" => {
            text(node, "name")?;
        }
        "path" => {
            text(node, "root")?;
            for item in array(node, "path")? {
                item.as_str().ok_or("PATH_ITEM")?;
            }
        }
        "not" => verify_expression(node.get("value").ok_or("NOT_VALUE")?)?,
        "and" | "or" => {
            for item in array(node, "values")? {
                verify_expression(item)?;
            }
        }
        "eq" | "ne" | "lt" | "le" | "gt" | "ge" => {
            verify_expression(node.get("left").ok_or("LEFT")?)?;
            verify_expression(node.get("right").ok_or("RIGHT")?)?;
        }
        "list" => {
            for item in array(node, "items")? {
                verify_expression(item)?;
            }
        }
        "map" => {
            for item in array(node, "items")? {
                let pair = item.as_array().ok_or("MAP_PAIR")?;
                if pair.len() != 2 {
                    return Err("MAP_PAIR_ARITY".to_string());
                }
                verify_expression(&pair[0])?;
                verify_expression(&pair[1])?;
            }
        }
        "call" => {
            if !matches!(
                text(node, "name")?,
                "len" | "all_equal" | "contains" | "add" | "get"
            ) {
                return Err("CALL_NOT_ALLOWED".to_string());
            }
            for item in array(node, "args")? {
                verify_expression(item)?;
            }
        }
        op => return Err(format!("UNKNOWN_EXPRESSION:{op}")),
    }
    Ok(())
}

fn verify_block(
    code: &[Value],
    declared_effects: &[String],
    capabilities: &[String],
) -> Result<(), String> {
    for instruction in code {
        match text(instruction, "op")? {
            "require" | "ensure" => {
                verify_expression(instruction.get("condition").ok_or("CONDITION")?)?;
                if instruction.get("error").is_none() {
                    return Err("ERROR_VALUE".to_string());
                }
            }
            "cancel_if" | "return_ok" | "return_error" | "emit_event" => {
                verify_expression(instruction.get("value").ok_or("VALUE")?)?
            }
            "let" | "set_state" => {
                text(instruction, "name")?;
                verify_expression(instruction.get("value").ok_or("VALUE")?)?;
            }
            "request_effect" => {
                let effect = text(instruction, "effect")?.to_string();
                if !declared_effects.contains(&effect) || !capabilities.contains(&effect) {
                    return Err("UNDECLARED_EFFECT".to_string());
                }
            }
            "if" => {
                verify_expression(instruction.get("condition").ok_or("CONDITION")?)?;
                verify_block(array(instruction, "then")?, declared_effects, capabilities)?;
                verify_block(array(instruction, "else")?, declared_effects, capabilities)?;
            }
            "for" => {
                text(instruction, "name")?;
                let limit = instruction
                    .get("limit")
                    .and_then(Value::as_u64)
                    .ok_or("LOOP_LIMIT")?;
                if limit == 0 || limit > 65_536 {
                    return Err("LOOP_LIMIT_RANGE".to_string());
                }
                verify_expression(instruction.get("iterable").ok_or("ITERABLE")?)?;
                verify_block(array(instruction, "body")?, declared_effects, capabilities)?;
            }
            "spawn_job" => {
                text(instruction, "name")?;
                let limit = instruction
                    .get("limit")
                    .and_then(Value::as_u64)
                    .ok_or("JOB_LIMIT")?;
                if limit == 0 || limit > 65_536 {
                    return Err("JOB_LIMIT_RANGE".to_string());
                }
                verify_expression(instruction.get("payload").ok_or("PAYLOAD")?)?;
            }
            "join_job" => {
                text(instruction, "name")?;
            }
            "match" => {
                verify_expression(instruction.get("value").ok_or("VALUE")?)?;
                let cases = array(instruction, "cases")?;
                if cases.is_empty() {
                    return Err("EMPTY_MATCH".to_string());
                }
                for case in cases {
                    text(case, "label")?;
                    verify_block(array(case, "body")?, declared_effects, capabilities)?;
                }
            }
            op => return Err(format!("UNKNOWN_OPCODE:{op}")),
        }
    }
    Ok(())
}
