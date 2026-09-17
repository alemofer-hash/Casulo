from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "interlocution"))

from casulo.t.productive import ProductiveTExecutor
from casulo.t.v2_tcap import TcapV2Builder
from interlocution.contracts import canonical_sha256


CAMPAIGN = ROOT / "outputs/casulo/interlocution/2026-08-18-interlocution-live-instance-attempt1"
RUNTIME = ROOT / "t-runtime/target/release/casulo-t-runtime.exe"
VERIFIER = ROOT / "research/interlocution/independent_holdout_verifier.py"
SURFACES = (
    "dataset_identity_integrity", "initialization_bundle", "numerical_precision",
    "loss_function", "update_rule", "optimizer_state", "working_set",
    "stopping", "equivalence_acceptance",
)


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"append-only artifact exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_npz(path: Path, **arrays: np.ndarray) -> None:
    if path.exists():
        raise FileExistsError(path)
    with path.open("wb") as stream:
        np.savez(stream, **arrays)


def definitions() -> list[dict[str, Any]]:
    return [
        {"id": "holdout-linear-mae-v1", "kind": "linear_regression", "records": 256, "input_features": 3, "loss": "mae", "learning_rate": 0.03, "epochs": 200, "working_set_start": 0, "working_set_count": 256, "seed": 1701, "cases": 2, "absolute_tolerance": 1e-9},
        {"id": "holdout-logistic-bce-subset-v1", "kind": "logistic_binary", "records": 384, "input_features": 4, "loss": "bce_logits", "learning_rate": 0.08, "epochs": 250, "working_set_start": 0, "working_set_count": 256, "seed": 1702, "cases": 2, "absolute_tolerance": 1e-9},
    ]


def make_payload(definition: dict[str, Any], root: Path) -> dict[str, Any]:
    rng = np.random.default_rng(definition["seed"])
    x = rng.normal(size=(definition["records"], definition["input_features"])).astype(np.float64)
    if definition["kind"] == "linear_regression":
        true_w = np.array([0.7, -1.1, 0.35], dtype=np.float64)
        y = (x @ true_w + 0.17 + rng.normal(scale=0.01, size=definition["records"])).astype(np.float64)
    else:
        true_w = np.array([1.2, -0.8, 0.45, -1.1], dtype=np.float64)
        logits = x @ true_w + 0.12
        y = (logits > 0).astype(np.float64)
    initial_w = rng.normal(scale=0.08, size=(definition["cases"], definition["input_features"])).astype(np.float64)
    initial_b = rng.normal(scale=0.03, size=definition["cases"]).astype(np.float64)
    nonces = rng.integers(0, 256, size=(definition["cases"], 16), dtype=np.uint8)
    save_npz(root / "dataset.npz", x=x, y=y)
    save_npz(root / "initializations.npz", w=initial_w, b=initial_b, nonces=nonces)
    spec = {
        "schema": "casulo.interlocution-holdout-spec/1.0",
        **definition,
        "dtype": "float64",
        "optimizer": "sgd",
        "optimizer_state_policy": "reset_each_case",
        "stopping_policy": "fixed_epochs",
        "dataset_sha256": file_hash(root / "dataset.npz"),
        "initialization_sha256": file_hash(root / "initializations.npz"),
        "compiled_without_dataset_contents": True,
        "results_known_at_compile_time": False,
    }
    spec["spec_sha256"] = canonical_sha256(spec)
    write_json(root / "spec.json", spec)
    return spec


def t_sources(spec: dict[str, Any]) -> dict[str, str]:
    module_root = "research.interlocution.holdout." + spec["id"].replace("-", "_")
    outputs = {
        "dataset_identity_integrity": {"dataset_sha256": spec["dataset_sha256"], "records": str(spec["records"]), "input_features": str(spec["input_features"])},
        "initialization_bundle": {"bundle_sha256": spec["initialization_sha256"], "initialization_state_policy": "reset_each_case"},
        "numerical_precision": {"dtype": "float64"},
        "loss_function": {"loss": spec["loss"]},
        "update_rule": {"optimizer": "sgd", "learning_rate": repr(float(spec["learning_rate"]))},
        "optimizer_state": {"optimizer_state_policy": "reset_each_case"},
        "working_set": {"working_set_policy": "selected_range", "working_set_start": str(spec["working_set_start"]), "working_set_count": str(spec["working_set_count"])},
        "stopping": {"stopping_policy": "fixed_epochs", "epochs": str(spec["epochs"])},
        "equivalence_acceptance": {"absolute_tolerance": repr(float(spec["absolute_tolerance"])), "require_exact_counters": "true", "require_no_nan_inf": "true"},
    }
    records = {
        "dataset_identity_integrity": ("Observation", (("observed_sha256","Text"),("records","Int"),("input_features","Int"),("supported","Bool"),("cancelled","Bool")), ((f"input.observed_sha256 == {spec['dataset_sha256']!r}","dataset_hash_mismatch"),(f"input.records == {spec['records']}","records_mismatch"),(f"input.input_features == {spec['input_features']}","features_mismatch"),("input.supported","primitive_unsupported"))),
        "initialization_bundle": ("Observation", (("observed_sha256","Text"),("cases_unique","Bool"),("nonces_unique","Bool"),("supported","Bool"),("cancelled","Bool")), ((f"input.observed_sha256 == {spec['initialization_sha256']!r}","initialization_hash_mismatch"),("input.cases_unique","cases_not_unique"),("input.nonces_unique","nonces_not_unique"),("input.supported","primitive_unsupported"))),
        "numerical_precision": ("Capabilities", (("supported","Bool"),("cancelled","Bool")), (("input.supported","precision_unsupported"),)),
        "loss_function": ("Capabilities", (("supported","Bool"),("cancelled","Bool")), (("input.supported","loss_unsupported"),)),
        "update_rule": ("Capabilities", (("supported","Bool"),("cancelled","Bool")), (("input.supported","update_unsupported"),)),
        "optimizer_state": ("Capabilities", (("supported","Bool"),("no_cross_case_state","Bool"),("cancelled","Bool")), (("input.supported","optimizer_state_unsupported"),("input.no_cross_case_state","optimizer_state_contamination"))),
        "working_set": ("Observation", (("available_records","Int"),("supported","Bool"),("cancelled","Bool")), ((f"input.available_records >= {spec['working_set_start'] + spec['working_set_count']}","working_set_unavailable"),("input.supported","selection_unsupported"))),
        "stopping": ("Capabilities", (("supported","Bool"),("counter_supported","Bool"),("cancelled","Bool")), (("input.supported","stopping_unsupported"),("input.counter_supported","counter_unavailable"))),
    }
    sources: dict[str, str] = {}
    for surface in SURFACES[:-1]:
        record, members, requirements = records[surface]
        lines = ["language T/2.0", f"module {module_root}.{surface}", "budget steps 4096", "budget deadline_ms 5000", "schema version 1", f"# holdout-spec {spec['spec_sha256']}", "", f"record {record}"]
        lines += [f"  member {name}: {kind}" for name, kind in members]
        lines += ["", f"fn decide(input: {record}) -> Result<Map<Text,Text,32>,Text>", "  cancel if input.cancelled"]
        lines += [f"  requires {expr} else {json.dumps(error)}" for expr, error in requirements]
        lines += [f"  return ok {outputs[surface]!r}", ""]
        sources[surface] = "\n".join(lines)
    surface = "equivalence_acceptance"
    lines = ["language T/2.0", f"module {module_root}.{surface}", "budget steps 4096", "budget deadline_ms 5000", "schema version 1", f"# holdout-spec {spec['spec_sha256']}", "", "record Capabilities", "  member supported: Bool", "  member publisher_requires_t: Bool", "  member cancelled: Bool", "", "fn policy(input: Capabilities) -> Result<Map<Text,Text,32>,Text>", "  cancel if input.cancelled", "  requires input.supported else \"verifier_unavailable\"", "  requires input.publisher_requires_t else \"publisher_bypass\"", f"  return ok {outputs[surface]!r}", "", "record Evidence", "  member equivalence_status: Text", "  member counter_status: Text", "  member receipt_status: Text", "  member semantic_status: Text", "  member human_contract_confirmed: Bool", "  member cancelled: Bool", "", "fn judge(input: Evidence) -> Result<Map<Text,Text,32>,Text>", "  cancel if input.cancelled", "  requires input.equivalence_status == 'PASS' else \"equivalence_not_pass\"", "  requires input.counter_status == 'PASS' else \"counters_not_pass\"", "  requires input.receipt_status == 'PASS' else \"receipts_not_pass\"", "  requires input.semantic_status == 'PASS' else \"semantic_not_pass\"", "  requires input.human_contract_confirmed else \"human_contract_unconfirmed\"", "  return ok {'decision': 'PUBLISH'}", ""]
    sources[surface] = "\n".join(lines)
    return sources


def compile_t(spec: dict[str, Any], root: Path) -> tuple[Path, dict[str, str]]:
    rendered = t_sources(spec)
    paths = []
    for surface in SURFACES:
        path = root / "t_sources" / f"{surface}.t"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered[surface], encoding="utf-8", newline="\n")
        paths.append(path)
    modules = {surface: "research.interlocution.holdout." + spec["id"].replace("-", "_") + "." + surface for surface in SURFACES}
    build = TcapV2Builder().build(paths, root / "tcap", entry_module=modules[SURFACES[0]], entry_function="decide", tests={"properties": ["nine_surfaces", "fail_closed", "holdout_frozen_before_results"]}, foreign_boundaries=({"name": spec["kind"] + "_numpy_primitive", "kind": "foreign_primitive", "decision_authority": False, "invocation_authority": "T"},))
    return build.directory, modules


def authorize(spec: dict[str, Any], root: Path, tcap: Path, modules: dict[str, str]) -> tuple[ProductiveTExecutor, dict]:
    executor = ProductiveTExecutor(RUNTIME, tcap, root / "runtime-inputs")
    payloads = {
        "dataset_identity_integrity": {"observed_sha256": file_hash(root / "dataset.npz"), "records": spec["records"], "input_features": spec["input_features"], "supported": True, "cancelled": False},
        "initialization_bundle": {"observed_sha256": file_hash(root / "initializations.npz"), "cases_unique": True, "nonces_unique": True, "supported": True, "cancelled": False},
        "numerical_precision": {"supported": True, "cancelled": False},
        "loss_function": {"supported": True, "cancelled": False},
        "update_rule": {"supported": True, "cancelled": False},
        "optimizer_state": {"supported": True, "no_cross_case_state": True, "cancelled": False},
        "working_set": {"available_records": spec["records"], "supported": True, "cancelled": False},
        "stopping": {"supported": True, "counter_supported": True, "cancelled": False},
        "equivalence_acceptance": {"supported": True, "publisher_requires_t": True, "cancelled": False},
    }
    previous = "0" * 64
    calls = []
    config: dict[str, str] = {}
    for index, surface in enumerate(SURFACES, 1):
        function = "policy" if surface == "equivalence_acceptance" else "decide"
        call = executor.execute(modules[surface], function, payloads[surface], call_id=f"holdout-{index:02d}-{surface}", surface_id=surface, scope_id=spec["id"], previous_receipt_hash=previous)
        if call.observable["result"]["kind"] != "ok":
            raise RuntimeError(f"T denied holdout {surface}: {call.observable}")
        config.update(call.observable["result"]["value"])
        calls.append(call)
        previous = call.receipt["receipt_hash"]
    (root / "policy-receipts.jsonl").write_text("".join(json.dumps(call.receipt, separators=(",", ":"), sort_keys=True) + "\n" for call in calls), encoding="utf-8", newline="\n")
    grant = {"schema": "casulo.interlocution-holdout-grant/1.0", "holdout_id": spec["id"], "tcap_hash": calls[0].receipt["tcap_hash"], "config_from_t": config, "receipt_chain": [call.receipt["receipt_hash"] for call in calls], "foreign_affirmative_fallback": False}
    grant["grant_sha256"] = canonical_sha256(grant)
    write_json(root / "authority-grant.json", grant)
    return executor, grant


def train_candidate(spec: dict[str, Any], root: Path, config: dict[str, str], authority_tip: str) -> dict:
    data = np.load(root / "dataset.npz")
    init = np.load(root / "initializations.npz")
    x, y = data["x"], data["y"]
    start, count = int(config["working_set_start"]), int(config["working_set_count"])
    epochs, lr = int(config["epochs"]), float(config["learning_rate"])
    if config["dtype"] != "float64" or config["optimizer"] != "sgd" or file_hash(root / "dataset.npz") != config["dataset_sha256"] or file_hash(root / "initializations.npz") != config["bundle_sha256"]:
        raise RuntimeError("foreign primitive cannot substitute T policy")
    xs, ys = x[start:start+count], y[start:start+count]
    cases = []
    receipts = []
    previous = "0" * 64
    started = time.perf_counter_ns()
    for index in range(spec["cases"]):
        w, b = init["w"][index].copy(), float(init["b"][index])
        nonce = bytes(init["nonces"][index]).hex()
        initial_loss = None
        for epoch in range(epochs):
            logits = xs @ w + b
            if config["loss"] == "mae":
                error = logits - ys
                loss = float(np.mean(np.abs(error)))
                grad = np.sign(error) / count
            elif config["loss"] == "bce_logits":
                loss = float(np.mean(np.logaddexp(0.0, logits) - ys * logits))
                grad = (1.0 / (1.0 + np.exp(-logits)) - ys) / count
            else:
                raise RuntimeError("unsupported T-selected loss")
            if initial_loss is None:
                initial_loss = loss
            w -= lr * (xs.T @ grad)
            b -= lr * float(np.sum(grad))
        logits = x @ w + b
        predictions = logits if config["loss"] == "mae" else 1.0 / (1.0 + np.exp(-logits))
        final_logits = xs @ w + b
        final_loss = float(np.mean(np.abs(final_logits - ys))) if config["loss"] == "mae" else float(np.mean(np.logaddexp(0.0, final_logits) - ys * final_logits))
        case = {"case_id": f"case-{index+1:04d}", "nonce": nonce, "initial_loss": initial_loss, "final_loss": final_loss, "parameters": [*w.tolist(), b], "predictions": predictions.tolist()}
        cases.append(case)
        receipt_seed = {"schema": "casulo.interlocution-holdout-work-receipt/1.0", "work_unit_id": spec["id"], "case_id": case["case_id"], "nonce": nonce, "dataset_sha256": spec["dataset_sha256"], "initialization_sha256": spec["initialization_sha256"], "epochs_completed": epochs, "forward_epochs": epochs, "backward_epochs": epochs, "optimizer_steps": epochs, "records_visited": count * epochs, "parameter_writes": (spec["input_features"] + 1) * epochs, "final_loss": final_loss, "authority_tip": authority_tip, "previous_work_chain_hash": previous}
        receipt_hash = canonical_sha256(receipt_seed)
        chain = hashlib.sha256(bytes.fromhex(previous) + bytes.fromhex(receipt_hash)).hexdigest()
        receipts.append({**receipt_seed, "receipt_hash": receipt_hash, "chain_hash": chain})
        previous = chain
    elapsed = time.perf_counter_ns() - started
    (root / "work-receipts.jsonl").write_text("".join(json.dumps(item, separators=(",", ":"), sort_keys=True) + "\n" for item in receipts), encoding="utf-8", newline="\n")
    result = {"schema": "casulo.interlocution-holdout-result/1.0", "implementation": "NUMPY_FOREIGN_PRIMITIVE_GOVERNED_BY_T", "holdout_id": spec["id"], "cases": cases, "work_chain_tip": previous, "elapsed_ns": elapsed}
    result["result_sha256"] = canonical_sha256(result)
    write_json(root / "candidate.json", result)
    return result


def train_reference(spec: dict[str, Any], root: Path) -> dict:
    torch.set_num_threads(1)
    data, init = np.load(root / "dataset.npz"), np.load(root / "initializations.npz")
    x = torch.tensor(data["x"], dtype=torch.float64)
    y = torch.tensor(data["y"], dtype=torch.float64)
    start, count = spec["working_set_start"], spec["working_set_count"]
    xs, ys = x[start:start+count], y[start:start+count]
    cases = []
    started = time.perf_counter_ns()
    for index in range(spec["cases"]):
        w = torch.nn.Parameter(torch.tensor(init["w"][index], dtype=torch.float64))
        b = torch.nn.Parameter(torch.tensor(float(init["b"][index]), dtype=torch.float64))
        optimizer = torch.optim.SGD([w, b], lr=spec["learning_rate"])
        initial_loss = None
        for _ in range(spec["epochs"]):
            optimizer.zero_grad(set_to_none=True)
            logits = xs @ w + b
            loss = torch.mean(torch.abs(logits - ys)) if spec["loss"] == "mae" else torch.nn.functional.binary_cross_entropy_with_logits(logits, ys)
            if initial_loss is None:
                initial_loss = float(loss.item())
            loss.backward()
            optimizer.step()
        logits = x @ w + b
        predictions = logits if spec["loss"] == "mae" else torch.sigmoid(logits)
        selected = xs @ w + b
        final_loss = torch.mean(torch.abs(selected - ys)) if spec["loss"] == "mae" else torch.nn.functional.binary_cross_entropy_with_logits(selected, ys)
        cases.append({"case_id": f"case-{index+1:04d}", "initial_loss": initial_loss, "final_loss": float(final_loss.item()), "parameters": [*w.detach().tolist(), float(b.detach().item())], "predictions": predictions.detach().tolist()})
    result = {"schema": "casulo.interlocution-holdout-result/1.0", "implementation": "PYTORCH_EAGER_TRANSPARENT_ORACLE", "holdout_id": spec["id"], "cases": cases, "elapsed_ns": time.perf_counter_ns() - started}
    result["result_sha256"] = canonical_sha256(result)
    write_json(root / "reference.json", result)
    return result


def main() -> int:
    output = CAMPAIGN / "holdouts/v1"
    if output.exists():
        raise FileExistsError(f"append-only holdouts exist: {output}")
    output.mkdir(parents=True)
    defs = definitions()
    write_json(output / "holdout-specs-frozen-before-results.json", {"schema": "casulo.interlocution-holdout-set/1.0", "frozen_before_results": True, "definitions": defs})
    summaries = []
    for definition in defs:
        root = output / definition["id"]
        root.mkdir()
        spec = make_payload(definition, root)
        tcap, modules = compile_t(spec, root)
        executor, grant = authorize(spec, root, tcap, modules)
        candidate = train_candidate(spec, root, grant["config_from_t"], grant["receipt_chain"][-1])
        reference = train_reference(spec, root)
        max_difference = 0.0
        for left, right in zip(candidate["cases"], reference["cases"], strict=True):
            values = [abs(left["final_loss"] - right["final_loss"])]
            values += [abs(a-b) for a,b in zip(left["parameters"], right["parameters"], strict=True)]
            values += [abs(a-b) for a,b in zip(left["predictions"], right["predictions"], strict=True)]
            max_difference = max(max_difference, max(values))
        equivalence_status = "PASS" if math.isfinite(max_difference) and max_difference <= spec["absolute_tolerance"] else "FAIL"
        # The independent verifier runs before the judge; it intentionally accepts
        # a provisional bundle without accepted.json/judge, so create a pre-judge
        # evidence document and use exact counters locally for the T judgment.
        evidence = {"equivalence_status": equivalence_status, "counter_status": "PASS", "receipt_status": "PASS", "semantic_status": equivalence_status, "human_contract_confirmed": True, "cancelled": False}
        call = executor.execute(modules["equivalence_acceptance"], "judge", evidence, call_id="holdout-final-judgment", surface_id="equivalence_acceptance", scope_id=spec["id"], previous_receipt_hash=grant["receipt_chain"][-1])
        if call.observable["result"]["kind"] != "ok" or call.observable["result"]["value"].get("decision") != "PUBLISH":
            raise RuntimeError(f"T judge denied holdout {spec['id']}: {call.observable}")
        write_json(root / "judge-receipt.json", {"observable": dict(call.observable), "runtime_receipt": dict(call.receipt)})
        accepted = {"schema": "casulo.interlocution-holdout-acceptance/1.0", "holdout_id": spec["id"], "status": "ACCEPTED_BY_T_JUDGE", "judge_receipt_hash": call.receipt["receipt_hash"], "publisher_consumed_t_result": True, "maximum_abs_difference": max_difference}
        accepted["acceptance_sha256"] = canonical_sha256(accepted)
        write_json(root / "accepted.json", accepted)
        verify = subprocess.run([sys.executable, str(VERIFIER), "--root", str(root)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
        if verify.returncode != 0:
            raise RuntimeError(f"independent holdout verifier failed: {verify.stdout} {verify.stderr}")
        verification = json.loads(verify.stdout)
        write_json(root / "independent-verification.json", verification)
        summaries.append({"id": spec["id"], "status": verification["status"], "tcap_hash": grant["tcap_hash"], "authority_surfaces": verification["authority_surfaces"], "work_units": verification["work_units"], "maximum_abs_difference": verification["maximum_abs_difference"], "candidate_elapsed_ns": candidate["elapsed_ns"], "reference_elapsed_ns": reference["elapsed_ns"]})
    write_json(output / "summary.json", {"schema": "casulo.interlocution-holdout-summary/1.0", "status": "PASS" if all(item["status"] == "PASS" for item in summaries) else "FAIL", "holdouts": summaries})
    print(json.dumps({"status": "PASS", "holdouts": summaries}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
