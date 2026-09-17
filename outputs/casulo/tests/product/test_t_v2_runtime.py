from __future__ import annotations

import json
from pathlib import Path

import pytest

from casulo.t.v2_runtime import V2ReferenceRuntime
from casulo.t.v2_tcap import TcapV2Builder, TcapV2Error, verify_tcap_v2


ROOT = Path(__file__).resolve().parents[2]


def build(tmp_path: Path):
    return TcapV2Builder().build(
        (ROOT / "examples/t-v2/owner_publish.t",),
        tmp_path / "publish.tcap",
        entry_module="owner.publish",
        entry_function="decide",
        tests={"properties":["hard_unknown_never_publishes","capability_required"]},
    )


def execute(tmp_path: Path, payload: dict, grants: frozenset[str] = frozenset({"manifest"})):
    built=build(tmp_path);_,manifest,typed=verify_tcap_v2(built.directory);ir=typed["modules"][0]
    return V2ReferenceRuntime().execute(ir,"decide",payload,grants=grants,source_hash=manifest["sources"][0]["sha256"],tcap_hash=built.tcap_hash,scope_id="creation:test",surface_id="publish_commit")


def valid_payload() -> dict:
    return {"confirmed":True,"hard_statuses":["PASS","PASS"],"cancelled":False}


def test_tcap_v2_contains_all_required_sections_and_functional_code(tmp_path: Path) -> None:
    built=build(tmp_path);root,manifest,_=verify_tcap_v2(built.directory)
    assert len(manifest["sections"])==14
    code=json.loads((root/"code.json").read_text(encoding="utf-8"))
    assert len(code["modules"][0]["functions"][0]["code"]) >= 8
    assert code["modules"][0]["functions"][0]["code"] != [{"op":"ret"}]


def test_reference_runtime_executes_state_loop_job_effect_and_receipt(tmp_path: Path) -> None:
    result=execute(tmp_path,valid_payload())
    assert result.result=={"kind":"ok","value":"PUBLISH"}
    assert result.state_delta=={"attempts":1}
    assert result.requested_effects==("manifest",)
    assert result.jobs[0]["status"]=="joined"
    assert result.receipt.runtime_id=="t-runtime/reference-2.0"
    assert result.receipt.surface_id=="publish_commit"


@pytest.mark.parametrize(
    ("payload","error"),
    [
        ({"confirmed":False,"hard_statuses":["PASS"],"cancelled":False},"intent_unconfirmed"),
        ({"confirmed":True,"hard_statuses":["UNKNOWN"],"cancelled":False},"hard_requirement_not_pass"),
        ({"confirmed":True,"hard_statuses":["PASS"],"cancelled":True},"CANCELLED"),
    ],
)
def test_runtime_fails_closed_before_publish(tmp_path: Path,payload: dict,error: str) -> None:
    result=execute(tmp_path,payload)
    assert result.result=={"kind":"error","value":error}
    assert result.requested_effects==()


def test_runtime_denies_missing_capability(tmp_path: Path) -> None:
    result=execute(tmp_path,valid_payload(),frozenset())
    assert result.result=={"kind":"error","value":"CAPABILITY_DENIED:manifest"}


def test_tcap_v2_rejects_tamper_and_missing_section(tmp_path: Path) -> None:
    built=build(tmp_path);(built.directory/"code.json").write_text("{}",encoding="utf-8")
    with pytest.raises(TcapV2Error,match="hash inválido"):
        verify_tcap_v2(built.directory)
