from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from casulo.t.authority import canonical_sha256
from casulo.t.v2_runtime import V2ReferenceRuntime, V2RuntimeError
from casulo.t.v2_tcap import TcapV2Builder, TcapV2Error, verify_tcap_v2


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "t-runtime/target/release" / ("casulo-t-runtime.exe" if __import__("os").name == "nt" else "casulo-t-runtime")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _reseal(root: Path, changed_sections: tuple[str, ...]) -> None:
    manifest_path = root / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for section in changed_sections:
        file = root / manifest["sections"][section]["file"]
        manifest["sections"][section]["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    manifest["tcap_hash"] = canonical_sha256(
        {"schema": "casulo.tcap/2.0", "sections": manifest["sections"], "sources": manifest["sources"]}
    )
    _write_json(manifest_path, manifest)


def _build(tmp_path: Path) -> Path:
    return TcapV2Builder().build(
        (ROOT / "examples/t-v2/owner_publish.t",), tmp_path / "publish.tcap",
        entry_module="owner.publish", entry_function="decide",
    ).directory


def _run(root: Path, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    input_path = root.parent / "input.json"
    input_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return subprocess.run(
        [str(RUNTIME), str(root), "decide", str(input_path), "manifest"],
        capture_output=True, text=True, encoding="utf-8", timeout=15, check=False,
    )


def test_recomputed_hashes_cannot_hide_source_ir_divergence(tmp_path: Path) -> None:
    root = _build(tmp_path)
    source = root / "sources/owner.publish.t"
    source.write_text(source.read_text(encoding="utf-8").replace('return ok "PUBLISH"', 'return ok "ALTERED"'), encoding="utf-8")
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["sources"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest["tcap_hash"] = canonical_sha256({"schema":"casulo.tcap/2.0","sections":manifest["sections"],"sources":manifest["sources"]})
    _write_json(root / "MANIFEST.json", manifest)
    with pytest.raises(TcapV2Error, match="typed IR diverge"):
        verify_tcap_v2(root)


def test_recomputed_hashes_cannot_hide_malformed_opcode(tmp_path: Path) -> None:
    root = _build(tmp_path)
    for filename in ("typed-ir.json", "code.json"):
        value = json.loads((root / filename).read_text(encoding="utf-8"))
        value["modules"][0]["functions"][0]["code"][0]["op"] = "foreign_decision"
        _write_json(root / filename, value)
    _reseal(root, ("typed_ir", "functional_code"))
    with pytest.raises(TcapV2Error, match="typed IR diverge"):
        verify_tcap_v2(root)
    completed = _run(root, {"confirmed": True, "hard_statuses": ["PASS"], "cancelled": False})
    assert completed.returncode == 2
    assert "UNKNOWN_OPCODE:foreign_decision" in completed.stderr


def test_effect_escalation_is_rejected_before_execution(tmp_path: Path) -> None:
    root = _build(tmp_path)
    for filename in ("typed-ir.json", "code.json"):
        value = json.loads((root / filename).read_text(encoding="utf-8"))
        function = value["modules"][0]["functions"][0]
        function["effects"] = ["network"]
        request = next(item for item in function["code"] if item["op"] == "request_effect")
        request["effect"] = "network"
        _write_json(root / filename, value)
    _reseal(root, ("typed_ir", "functional_code"))
    completed = _run(root, {"confirmed": True, "hard_statuses": ["PASS"], "cancelled": False})
    assert completed.returncode == 2
    assert "UNDECLARED_EFFECT" in completed.stderr


def test_resource_exhaustion_has_same_error_state(tmp_path: Path) -> None:
    source = tmp_path / "exhaust.t"
    source.write_text(
        """language T/2.0
module test.exhaust
budget steps 1
budget deadline_ms 5000
schema version 1

record Input
  member cancelled: Bool

fn decide(input: Input) -> Result<Text,Text>
  cancel if input.cancelled
  return ok \"PASS\"
""",
        encoding="utf-8",
    )
    built = TcapV2Builder().build((source,), tmp_path / "exhaust.tcap", entry_module="test.exhaust", entry_function="decide")
    _, _, typed = verify_tcap_v2(built.directory)
    with pytest.raises(V2RuntimeError, match="RESOURCE_STEPS_EXHAUSTED"):
        V2ReferenceRuntime().execute(typed["modules"][0], "decide", {"cancelled": False})
    completed = _run(built.directory, {"cancelled": False})
    assert completed.returncode == 2
    assert "RESOURCE_STEPS_EXHAUSTED" in completed.stderr


def test_productive_receipt_is_complete_hash_valid_and_replay_stable(tmp_path: Path) -> None:
    root = _build(tmp_path)
    first = _run(root, {"confirmed": True, "hard_statuses": ["PASS"], "cancelled": False})
    second = _run(root, {"confirmed": True, "hard_statuses": ["PASS"], "cancelled": False})
    assert first.returncode == second.returncode == 0
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    receipt = first_payload["runtime_receipt"]
    required = {
        "schema", "decision_id", "surface_id", "scope_id", "t_source_hash", "t_ir_hash",
        "tcap_hash", "runtime_function", "canonical_input_hash", "canonical_output_hash",
        "effects_requested", "grants_consumed", "foreign_calls", "result",
        "previous_receipt_hash", "monotonic_timestamp_ns", "runtime_id", "receipt_hash",
    }
    assert set(receipt) == required
    seed = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    assert receipt["receipt_hash"] == canonical_sha256(seed)
    assert first_payload == second_payload


def test_future_tcap_schema_is_rejected_honestly(tmp_path: Path) -> None:
    root = _build(tmp_path)
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["schema"] = "casulo.tcap/3.0"
    _write_json(root / "MANIFEST.json", manifest)
    with pytest.raises(TcapV2Error, match="seções TCAP v2 incompletas"):
        verify_tcap_v2(root)
    completed = _run(root, {"confirmed": True, "hard_statuses": ["PASS"], "cancelled": False})
    assert completed.returncode == 2
    assert "schema invalid" in completed.stderr
