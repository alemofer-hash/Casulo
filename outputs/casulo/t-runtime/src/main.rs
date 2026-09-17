use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

fn sha(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn canonical(value: &Value) -> Vec<u8> {
    serde_json::to_vec(value).expect("canonical json")
}
fn fail(message: &str) -> ! {
    eprintln!("T_RUNTIME_ERROR:{message}");
    std::process::exit(2)
}

struct Control {
    steps: u64,
    max_steps: u64,
    started: Instant,
    deadline: Duration,
}
impl Control {
    fn tick(&mut self) -> Result<(), String> {
        self.steps += 1;
        if self.steps > self.max_steps {
            return Err("RESOURCE_STEPS_EXHAUSTED".into());
        }
        if self.started.elapsed() > self.deadline {
            return Err("DEADLINE_EXCEEDED".into());
        }
        Ok(())
    }
}

struct Machine {
    state: Map<String, Value>,
    initial: Map<String, Value>,
    env: BTreeMap<String, Value>,
    grants: Vec<String>,
    effects: Vec<String>,
    events: Vec<Value>,
    jobs: BTreeMap<String, Value>,
    diagnostics: Vec<String>,
    declared_effects: Vec<String>,
    capabilities: Vec<String>,
    control: Control,
}

impl Machine {
    fn eval(&mut self, node: &Value) -> Result<Value, String> {
        self.control.tick()?;
        let op = node["op"].as_str().ok_or("expression without op")?;
        match op {
            "const" => Ok(node["value"].clone()),
            "name" => self
                .env
                .get(node["name"].as_str().ok_or("name")?)
                .cloned()
                .ok_or("NAME_NOT_FOUND".into()),
            "path" => {
                let mut value = self
                    .env
                    .get(node["root"].as_str().ok_or("root")?)
                    .cloned()
                    .ok_or("ROOT_NOT_FOUND")?;
                for part in node["path"].as_array().ok_or("path")? {
                    value = value
                        .get(part.as_str().ok_or("path item")?)
                        .cloned()
                        .ok_or("FIELD_NOT_FOUND")?;
                }
                Ok(value)
            }
            "not" => Ok(Value::Bool(
                !self
                    .eval(&node["value"])?
                    .as_bool()
                    .ok_or("BOOL_EXPECTED")?,
            )),
            "and" | "or" => {
                let mut values = Vec::new();
                for item in node["values"].as_array().ok_or("values")? {
                    values.push(self.eval(item)?.as_bool().ok_or("BOOL_EXPECTED")?);
                }
                Ok(Value::Bool(if op == "and" {
                    values.iter().all(|v| *v)
                } else {
                    values.iter().any(|v| *v)
                }))
            }
            "eq" | "ne" | "lt" | "le" | "gt" | "ge" => {
                let left = self.eval(&node["left"])?;
                let right = self.eval(&node["right"])?;
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
                let mut values = Vec::new();
                for item in node["items"].as_array().ok_or("items")? {
                    values.push(self.eval(item)?);
                }
                Ok(Value::Array(values))
            }
            "map" => {
                let mut values = Map::new();
                for pair in node["items"].as_array().ok_or("items")? {
                    let p = pair.as_array().ok_or("pair")?;
                    let key = self.eval(&p[0])?.as_str().ok_or("map key")?.to_string();
                    values.insert(key, self.eval(&p[1])?);
                }
                Ok(Value::Object(values))
            }
            "call" => {
                let name = node["name"].as_str().ok_or("call name")?;
                let mut args = Vec::new();
                for item in node["args"].as_array().ok_or("args")? {
                    args.push(self.eval(item)?);
                }
                match name {
                    "len" => Ok(json!(
                        args[0]
                            .as_array()
                            .map(|x| x.len())
                            .or_else(|| args[0].as_object().map(|x| x.len()))
                            .or_else(|| args[0].as_str().map(|x| x.len()))
                            .ok_or("LEN_TYPE")?
                    )),
                    "all_equal" => Ok(Value::Bool(
                        args[0]
                            .as_array()
                            .ok_or("ALL_EQUAL_LIST")?
                            .iter()
                            .all(|v| v == &args[1]),
                    )),
                    "contains" => Ok(Value::Bool(
                        args[0]
                            .as_array()
                            .map(|x| x.contains(&args[1]))
                            .or_else(|| {
                                args[0]
                                    .as_str()
                                    .and_then(|x| args[1].as_str().map(|y| x.contains(y)))
                            })
                            .ok_or("CONTAINS_TYPE")?,
                    )),
                    "add" => {
                        if let (Some(a), Some(b)) = (args[0].as_i64(), args[1].as_i64()) {
                            Ok(json!(a + b))
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
                    _ => Err("CALL_NOT_ALLOWED".into()),
                }
            }
            _ => Err(format!("UNKNOWN_EXPRESSION:{op}")),
        }
    }

    fn block(&mut self, code: &[Value]) -> Result<Option<Value>, String> {
        for instruction in code {
            self.control.tick()?;
            let op = instruction["op"].as_str().ok_or("instruction without op")?;
            match op {
                "require" | "ensure" => {
                    if !self
                        .eval(&instruction["condition"])?
                        .as_bool()
                        .ok_or("BOOL_EXPECTED")?
                    {
                        return Ok(Some(
                            json!({"kind":"error","value":instruction["error"].clone()}),
                        ));
                    }
                }
                "cancel_if" => {
                    if self
                        .eval(&instruction["value"])?
                        .as_bool()
                        .ok_or("BOOL_EXPECTED")?
                    {
                        return Ok(Some(json!({"kind":"error","value":"CANCELLED"})));
                    }
                }
                "let" => {
                    let value = self.eval(&instruction["value"])?;
                    self.env
                        .insert(instruction["name"].as_str().ok_or("name")?.into(), value);
                }
                "set_state" => {
                    let name = instruction["name"]
                        .as_str()
                        .ok_or("state name")?
                        .to_string();
                    let value = self.eval(&instruction["value"])?;
                    self.state.insert(name.clone(), value);
                    self.env
                        .insert("state".into(), Value::Object(self.state.clone()));
                }
                "request_effect" => {
                    let effect = instruction["effect"].as_str().ok_or("effect")?.to_string();
                    if !self.declared_effects.contains(&effect)
                        || !self.capabilities.contains(&effect)
                    {
                        return Err("UNDECLARED_EFFECT".into());
                    }
                    if !self.grants.contains(&effect) {
                        return Ok(Some(
                            json!({"kind":"error","value":format!("CAPABILITY_DENIED:{effect}")}),
                        ));
                    }
                    self.effects.push(effect);
                }
                "emit_event" => {
                    let value = self.eval(&instruction["value"])?;
                    self.events.push(value);
                }
                "return_ok" => {
                    return Ok(Some(
                        json!({"kind":"ok","value":self.eval(&instruction["value"])?}),
                    ));
                }
                "return_error" => {
                    return Ok(Some(
                        json!({"kind":"error","value":self.eval(&instruction["value"])?}),
                    ));
                }
                "if" => {
                    let chosen = if self
                        .eval(&instruction["condition"])?
                        .as_bool()
                        .ok_or("BOOL_EXPECTED")?
                    {
                        &instruction["then"]
                    } else {
                        &instruction["else"]
                    };
                    if let Some(value) = self.block(chosen.as_array().ok_or("if body")?)? {
                        return Ok(Some(value));
                    }
                }
                "for" => {
                    let values = self.eval(&instruction["iterable"])?;
                    let array = values.as_array().ok_or("FOR_EXPECTED_LIST")?;
                    let limit = instruction["limit"].as_u64().ok_or("limit")? as usize;
                    if array.len() > limit {
                        return Ok(Some(
                            json!({"kind":"error","value":"COLLECTION_BOUND_EXCEEDED"}),
                        ));
                    }
                    for value in array {
                        let name = instruction["name"].as_str().ok_or("for name")?.to_string();
                        let old = self.env.insert(name.clone(), value.clone());
                        if let Some(result) =
                            self.block(instruction["body"].as_array().ok_or("for body")?)?
                        {
                            return Ok(Some(result));
                        }
                        if let Some(previous) = old {
                            self.env.insert(name, previous);
                        } else {
                            self.env.remove(&name);
                        }
                    }
                }
                "spawn_job" => {
                    let name = instruction["name"].as_str().ok_or("job name")?.to_string();
                    if self.jobs.contains_key(&name) {
                        return Ok(Some(json!({"kind":"error","value":"JOB_ALREADY_EXISTS"})));
                    }
                    let payload = self.eval(&instruction["payload"])?;
                    let job = json!({"name":name,"status":"spawned","payload":payload,"limit":instruction["limit"]});
                    self.jobs.insert(name.clone(), job.clone());
                    self.env.insert(name, job);
                }
                "join_job" => {
                    let name = instruction["name"].as_str().ok_or("job name")?.to_string();
                    let job = self.jobs.get_mut(&name).ok_or("JOB_NOT_FOUND")?;
                    job["status"] = json!("joined");
                }
                "match" => {
                    let value = self.eval(&instruction["value"])?;
                    let label = if let Some(v) = value.as_bool() {
                        v.to_string()
                    } else if let Some(v) = value.as_str() {
                        v.to_string()
                    } else {
                        value.to_string()
                    };
                    let cases = instruction["cases"].as_array().ok_or("cases")?;
                    let case = cases
                        .iter()
                        .find(|c| c["label"] == label)
                        .or_else(|| cases.iter().find(|c| c["label"] == "_"))
                        .ok_or("NON_EXHAUSTIVE_MATCH")?;
                    if let Some(result) = self.block(case["body"].as_array().ok_or("case body")?)? {
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
    value.as_f64().ok_or("NUMBER_EXPECTED".into())
}

fn confined(root: &Path, relative: &str) -> Result<PathBuf, String> {
    let candidate = root.join(relative);
    let canonical = candidate.canonicalize().map_err(|_| "MISSING_SECTION")?;
    let base = root.canonicalize().map_err(|_| "INVALID_ROOT")?;
    if !canonical.starts_with(&base) {
        return Err("PATH_ESCAPE".into());
    }
    Ok(canonical)
}

fn verify_expression(node: &Value) -> Result<(), String> {
    let op = node["op"].as_str().ok_or("expression without op")?;
    match op {
        "const" => {
            if node.get("value").is_none() {
                return Err("CONST_VALUE".into());
            }
        }
        "name" => {
            node["name"].as_str().ok_or("NAME")?;
        }
        "path" => {
            node["root"].as_str().ok_or("ROOT")?;
            for item in node["path"].as_array().ok_or("PATH")? {
                item.as_str().ok_or("PATH_ITEM")?;
            }
        }
        "not" => verify_expression(&node["value"])?,
        "and" | "or" => {
            for item in node["values"].as_array().ok_or("VALUES")? {
                verify_expression(item)?;
            }
        }
        "eq" | "ne" | "lt" | "le" | "gt" | "ge" => {
            verify_expression(&node["left"])?;
            verify_expression(&node["right"])?;
        }
        "list" => {
            for item in node["items"].as_array().ok_or("ITEMS")? {
                verify_expression(item)?;
            }
        }
        "map" => {
            for item in node["items"].as_array().ok_or("ITEMS")? {
                let pair = item.as_array().ok_or("MAP_PAIR")?;
                if pair.len() != 2 {
                    return Err("MAP_PAIR_ARITY".into());
                }
                verify_expression(&pair[0])?;
                verify_expression(&pair[1])?;
            }
        }
        "call" => {
            let name = node["name"].as_str().ok_or("CALL_NAME")?;
            if !matches!(name, "len" | "all_equal" | "contains" | "add" | "get") {
                return Err("CALL_NOT_ALLOWED".into());
            }
            for item in node["args"].as_array().ok_or("ARGS")? {
                verify_expression(item)?;
            }
        }
        _ => return Err(format!("UNKNOWN_EXPRESSION:{op}")),
    }
    Ok(())
}

fn verify_block(
    code: &[Value],
    declared_effects: &[String],
    capabilities: &[String],
) -> Result<(), String> {
    for instruction in code {
        let op = instruction["op"].as_str().ok_or("instruction without op")?;
        match op {
            "require" | "ensure" => {
                verify_expression(&instruction["condition"])?;
                if instruction.get("error").is_none() {
                    return Err("ERROR_VALUE".into());
                }
            }
            "cancel_if" | "return_ok" | "return_error" | "emit_event" => {
                verify_expression(&instruction["value"])?
            }
            "let" | "set_state" => {
                instruction["name"].as_str().ok_or("NAME")?;
                verify_expression(&instruction["value"])?;
            }
            "request_effect" => {
                let effect = instruction["effect"].as_str().ok_or("EFFECT")?.to_string();
                if !declared_effects.contains(&effect) || !capabilities.contains(&effect) {
                    return Err("UNDECLARED_EFFECT".into());
                }
            }
            "if" => {
                verify_expression(&instruction["condition"])?;
                verify_block(
                    instruction["then"].as_array().ok_or("THEN")?,
                    declared_effects,
                    capabilities,
                )?;
                verify_block(
                    instruction["else"].as_array().ok_or("ELSE")?,
                    declared_effects,
                    capabilities,
                )?;
            }
            "for" => {
                instruction["name"].as_str().ok_or("FOR_NAME")?;
                let limit = instruction["limit"].as_u64().ok_or("LOOP_LIMIT")?;
                if limit == 0 || limit > 65536 {
                    return Err("LOOP_LIMIT_RANGE".into());
                }
                verify_expression(&instruction["iterable"])?;
                verify_block(
                    instruction["body"].as_array().ok_or("BODY")?,
                    declared_effects,
                    capabilities,
                )?;
            }
            "spawn_job" => {
                instruction["name"].as_str().ok_or("JOB_NAME")?;
                let limit = instruction["limit"].as_u64().ok_or("JOB_LIMIT")?;
                if limit == 0 || limit > 65536 {
                    return Err("JOB_LIMIT_RANGE".into());
                }
                verify_expression(&instruction["payload"])?;
            }
            "join_job" => {
                instruction["name"].as_str().ok_or("JOB_NAME")?;
            }
            "match" => {
                verify_expression(&instruction["value"])?;
                let cases = instruction["cases"].as_array().ok_or("CASES")?;
                if cases.is_empty() {
                    return Err("EMPTY_MATCH".into());
                }
                for case in cases {
                    case["label"].as_str().ok_or("CASE_LABEL")?;
                    verify_block(
                        case["body"].as_array().ok_or("CASE_BODY")?,
                        declared_effects,
                        capabilities,
                    )?;
                }
            }
            _ => return Err(format!("UNKNOWN_OPCODE:{op}")),
        }
    }
    Ok(())
}

fn safe_id(value: &str, max_len: usize, extra: &str) -> bool {
    !value.is_empty()
        && value.len() <= max_len
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || extra.contains(character))
}

fn valid_receipt_hash(value: &str) -> bool {
    value.len() == 64 && value.chars().all(|character| character.is_ascii_hexdigit())
}

fn execute_one(
    manifest: &Value,
    module: &Value,
    function: &Value,
    input: &Value,
    grants: &[String],
    surface: &str,
    scope: &str,
    previous: &str,
) -> Result<Value, String> {
    let input_obj = input.as_object().cloned().ok_or("input object")?;
    if !safe_id(surface, 128, "_.:-") {
        return Err("invalid surface id".into());
    }
    if !safe_id(scope, 128, "_.:-") {
        return Err("invalid scope id".into());
    }
    if !valid_receipt_hash(previous) {
        return Err("previous receipt hash".into());
    }
    let mut state = Map::new();
    for item in module["states"].as_array().ok_or("states")? {
        state.insert(
            item["name"].as_str().ok_or("state name")?.into(),
            item["initial"].clone(),
        );
    }
    let initial = state.clone();
    let mut envs = BTreeMap::new();
    envs.insert(
        function["parameter"]["name"]
            .as_str()
            .ok_or("parameter name")?
            .into(),
        Value::Object(input_obj),
    );
    envs.insert("state".into(), Value::Object(state.clone()));
    let declared_effects = function["effects"]
        .as_array()
        .ok_or("effects")?
        .iter()
        .map(|value| value.as_str().ok_or("effect type").map(str::to_string))
        .collect::<Result<Vec<_>, _>>()?;
    let capabilities = module["capabilities"]
        .as_array()
        .ok_or("capabilities")?
        .iter()
        .map(|value| value.as_str().ok_or("capability type").map(str::to_string))
        .collect::<Result<Vec<_>, _>>()?;
    let steps = module["budgets"]["steps"].as_u64().ok_or("step budget")?;
    let deadline_ms = module["budgets"]["deadline_ms"]
        .as_u64()
        .ok_or("deadline budget")?;
    if steps == 0 || steps > 10_000_000 || deadline_ms == 0 || deadline_ms > 60_000 {
        return Err("resource budget range".into());
    }
    let mut machine = Machine {
        state,
        initial,
        env: envs,
        grants: grants.to_vec(),
        effects: Vec::new(),
        events: Vec::new(),
        jobs: BTreeMap::new(),
        diagnostics: Vec::new(),
        declared_effects,
        capabilities,
        control: Control {
            steps: 0,
            max_steps: steps,
            started: Instant::now(),
            deadline: Duration::from_millis(deadline_ms),
        },
    };
    let result = machine
        .block(function["code"].as_array().ok_or("code")?)?
        .ok_or("missing return")?;
    let mut delta = Map::new();
    for (key, value) in &machine.state {
        if machine.initial.get(key) != Some(value) {
            delta.insert(key.clone(), value.clone());
        }
    }
    let observable = json!({
        "result": result,
        "state_delta": delta,
        "requested_effects": machine.effects,
        "events": machine.events,
        "jobs": machine.jobs.values().cloned().collect::<Vec<_>>(),
        "diagnostics": machine.diagnostics,
    });
    let output_hash = sha(&canonical(&observable));
    let input_hash = sha(&canonical(input));
    let entry_module = module["module"].as_str().ok_or("module name")?;
    let function_name = function["name"].as_str().ok_or("function name")?;
    let source_hash = manifest["sources"]
        .as_array()
        .and_then(|items| items.iter().find(|item| item["module"] == entry_module))
        .and_then(|item| item["sha256"].as_str())
        .ok_or("entry source hash")?;
    let ir_hash = sha(&canonical(module));
    let grants_consumed = observable["requested_effects"]
        .as_array()
        .ok_or("requested effects")?
        .iter()
        .filter(|effect| {
            grants
                .iter()
                .any(|grant| Some(grant.as_str()) == effect.as_str())
        })
        .cloned()
        .collect::<Vec<_>>();
    let receipt_seed = json!({
        "schema": "casulo.t-decision-receipt/2.0",
        "decision_id": format!("decision:{}", &output_hash[..24]),
        "surface_id": surface,
        "scope_id": scope,
        "t_source_hash": source_hash,
        "t_ir_hash": ir_hash,
        "tcap_hash": manifest["tcap_hash"],
        "runtime_function": format!("{}::{}", entry_module, function_name),
        "canonical_input_hash": input_hash,
        "canonical_output_hash": output_hash,
        "effects_requested": observable["requested_effects"],
        "grants_consumed": grants_consumed,
        "foreign_calls": [],
        "result": observable["result"]["kind"],
        "previous_receipt_hash": previous,
        "monotonic_timestamp_ns": 1,
        "runtime_id": "t-runtime/rust-2.0",
    });
    let mut receipt = receipt_seed.as_object().ok_or("receipt seed")?.clone();
    receipt.insert("receipt_hash".into(), json!(sha(&canonical(&receipt_seed))));
    Ok(json!({
        "observable": observable,
        "runtime_receipt": Value::Object(receipt),
    }))
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let batch = args.get(1).map(String::as_str) == Some("--batch");
    if (!batch && args.len() != 5 && args.len() != 8) || (batch && args.len() != 6) {
        fail(
            "usage [--batch] <tcap-dir> <function> <input-json> <grants-csv> [surface scope previous-receipt]",
        );
    }
    let offset = if batch { 2 } else { 1 };
    let root = Path::new(&args[offset]);
    let manifest_bytes =
        fs::read(root.join("MANIFEST.json")).unwrap_or_else(|_| fail("manifest missing"));
    let manifest: Value =
        serde_json::from_slice(&manifest_bytes).unwrap_or_else(|_| fail("manifest invalid"));
    if manifest["schema"] != "casulo.tcap/2.0" {
        fail("schema invalid");
    }
    for (_name, entry) in manifest["sections"]
        .as_object()
        .unwrap_or_else(|| fail("sections invalid"))
    {
        let file =
            confined(root, entry["file"].as_str().unwrap_or("")).unwrap_or_else(|e| fail(&e));
        let bytes = fs::read(file).unwrap_or_else(|_| fail("section read"));
        if sha(&bytes) != entry["sha256"].as_str().unwrap_or("") {
            fail("section hash");
        }
    }
    for entry in manifest["sources"]
        .as_array()
        .unwrap_or_else(|| fail("sources invalid"))
    {
        let file =
            confined(root, entry["file"].as_str().unwrap_or("")).unwrap_or_else(|e| fail(&e));
        let bytes = fs::read(file).unwrap_or_else(|_| fail("source read"));
        if sha(&bytes) != entry["sha256"].as_str().unwrap_or("") {
            fail("source hash");
        }
    }
    let tcap_seed = json!({"schema":"casulo.tcap/2.0","sections":manifest["sections"],"sources":manifest["sources"]});
    if sha(&canonical(&tcap_seed)) != manifest["tcap_hash"].as_str().unwrap_or("") {
        fail("tcap identity");
    }
    let typed_file = manifest["sections"]["typed_ir"]["file"]
        .as_str()
        .unwrap_or_else(|| fail("typed ir"));
    let typed: Value = serde_json::from_slice(
        &fs::read(confined(root, typed_file).unwrap_or_else(|e| fail(&e))).unwrap(),
    )
    .unwrap_or_else(|_| fail("typed ir parse"));
    if typed["schema"] != "casulo.t-ir-bundle/2.0" {
        fail("typed ir schema");
    }
    let code_file = manifest["sections"]["functional_code"]["file"]
        .as_str()
        .unwrap_or_else(|| fail("functional code"));
    let code: Value = serde_json::from_slice(
        &fs::read(confined(root, code_file).unwrap_or_else(|e| fail(&e))).unwrap(),
    )
    .unwrap_or_else(|_| fail("functional code parse"));
    if code["schema"] != "casulo.t-bytecode/2.0"
        || code["encoding"] != "structured-opcodes"
        || code["entry"] != manifest["entry"]
    {
        fail("functional code contract");
    }
    let manifest_entry_module = manifest["entry"]["module"]
        .as_str()
        .unwrap_or_else(|| fail("entry module"));
    let (entry_module, function_name) = args[offset + 1]
        .rsplit_once("::")
        .unwrap_or((manifest_entry_module, args[offset + 1].as_str()));
    let module = typed["modules"]
        .as_array()
        .unwrap_or_else(|| fail("modules"))
        .iter()
        .find(|m| m["module"] == entry_module)
        .unwrap_or_else(|| fail("module not found"));
    let function = module["functions"]
        .as_array()
        .unwrap_or_else(|| fail("functions"))
        .iter()
        .find(|f| f["name"] == function_name)
        .unwrap_or_else(|| fail("function not found"));
    let code_module = code["modules"]
        .as_array()
        .unwrap_or_else(|| fail("code modules"))
        .iter()
        .find(|m| m["name"] == entry_module)
        .unwrap_or_else(|| fail("code module not found"));
    let code_function = code_module["functions"]
        .as_array()
        .unwrap_or_else(|| fail("code functions"))
        .iter()
        .find(|f| f["name"] == function_name)
        .unwrap_or_else(|| fail("code function not found"));
    if code_function != function {
        fail("functional code differs from typed ir");
    }
    let declared_effects = function["effects"]
        .as_array()
        .unwrap_or_else(|| fail("effects"))
        .iter()
        .map(|v| {
            v.as_str()
                .unwrap_or_else(|| fail("effect type"))
                .to_string()
        })
        .collect::<Vec<_>>();
    let capabilities = module["capabilities"]
        .as_array()
        .unwrap_or_else(|| fail("capabilities"))
        .iter()
        .map(|v| {
            v.as_str()
                .unwrap_or_else(|| fail("capability type"))
                .to_string()
        })
        .collect::<Vec<_>>();
    verify_block(
        function["code"].as_array().unwrap_or_else(|| fail("code")),
        &declared_effects,
        &capabilities,
    )
    .unwrap_or_else(|e| fail(&e));
    let input: Value =
        serde_json::from_slice(&fs::read(&args[offset + 2]).unwrap_or_else(|_| fail("input read")))
            .unwrap_or_else(|_| fail("input json"));
    let grants = args[offset + 3]
        .split(',')
        .filter(|s| !s.is_empty())
        .map(String::from)
        .collect::<Vec<_>>();
    if batch {
        if input["schema"] != "casulo.t-runtime-batch/1.0" {
            fail("batch schema");
        }
        let calls = input["calls"]
            .as_array()
            .unwrap_or_else(|| fail("batch calls"));
        if calls.is_empty() || calls.len() > 65_536 {
            fail("batch cardinality");
        }
        let mut previous = input["previous_receipt_hash"]
            .as_str()
            .unwrap_or_else(|| fail("batch previous"))
            .to_string();
        if !valid_receipt_hash(&previous) {
            fail("batch previous receipt hash");
        }
        let mut outputs = Vec::with_capacity(calls.len());
        for call in calls {
            let call_id = call["call_id"]
                .as_str()
                .unwrap_or_else(|| fail("batch call id"));
            if !safe_id(call_id, 128, "_.-") {
                fail("batch call id");
            }
            let payload = call.get("payload").unwrap_or_else(|| fail("batch payload"));
            let surface = call["surface_id"]
                .as_str()
                .unwrap_or_else(|| fail("batch surface"));
            let scope = call["scope_id"]
                .as_str()
                .unwrap_or_else(|| fail("batch scope"));
            let output = execute_one(
                &manifest, module, function, payload, &grants, surface, scope, &previous,
            )
            .unwrap_or_else(|e| fail(&e));
            previous = output["runtime_receipt"]["receipt_hash"]
                .as_str()
                .unwrap_or_else(|| fail("batch receipt hash"))
                .to_string();
            let mut envelope = output
                .as_object()
                .unwrap_or_else(|| fail("batch output"))
                .clone();
            envelope.insert("call_id".into(), json!(call_id));
            outputs.push(Value::Object(envelope));
        }
        println!("{}",serde_json::to_string(&json!({"schema":"casulo.t-runtime-batch-result/1.0","calls":outputs,"receipt_chain_head":previous})).unwrap());
    } else {
        let surface = if args.len() == 8 {
            args[offset + 4].as_str()
        } else {
            "agent_behavior"
        };
        let scope = if args.len() == 8 {
            args[offset + 5].as_str()
        } else {
            "scope:test"
        };
        let previous = if args.len() == 8 {
            args[offset + 6].as_str()
        } else {
            "0000000000000000000000000000000000000000000000000000000000000000"
        };
        let output = execute_one(
            &manifest, module, function, &input, &grants, surface, scope, previous,
        )
        .unwrap_or_else(|e| fail(&e));
        println!("{}", serde_json::to_string(&output).unwrap());
    }
}
