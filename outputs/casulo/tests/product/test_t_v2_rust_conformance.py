from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from casulo.t.v2_runtime import V2ReferenceRuntime
from casulo.t.v2_tcap import TcapV2Builder, verify_tcap_v2


ROOT=Path(__file__).resolve().parents[2]
RUNTIME=ROOT/"t-runtime/target/release"/("casulo-t-runtime.exe" if __import__("os").name=="nt" else "casulo-t-runtime")


def run_pair(tmp_path:Path,payload:dict,grants:str="manifest"):
    built=TcapV2Builder().build((ROOT/"examples/t-v2/owner_publish.t",),tmp_path/"publish.tcap",entry_module="owner.publish",entry_function="decide")
    _,manifest,typed=verify_tcap_v2(built.directory);ir=typed["modules"][0]
    reference=V2ReferenceRuntime().execute(ir,"decide",payload,grants=frozenset(item for item in grants.split(",") if item),source_hash=manifest["sources"][0]["sha256"],tcap_hash=built.tcap_hash,scope_id="creation:test",surface_id="publish_commit")
    input_path=tmp_path/"input.json";input_path.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True),encoding="utf-8")
    completed=subprocess.run([str(RUNTIME),str(built.directory),"decide",str(input_path),grants],capture_output=True,text=True,encoding="utf-8",timeout=15,check=False)
    assert completed.returncode==0,completed.stderr
    productive=json.loads(completed.stdout)
    return reference.observable(),productive


@pytest.mark.parametrize("payload",[
    {"confirmed":True,"hard_statuses":["PASS","PASS"],"cancelled":False},
    {"confirmed":False,"hard_statuses":["PASS"],"cancelled":False},
    {"confirmed":True,"hard_statuses":["UNKNOWN"],"cancelled":False},
    {"confirmed":True,"hard_statuses":["PASS"],"cancelled":True},
])
def test_reference_and_rust_runtime_have_same_observables(tmp_path:Path,payload:dict)->None:
    reference,productive=run_pair(tmp_path,payload)
    assert productive["observable"]==reference
    assert productive["runtime_receipt"]["runtime_id"]=="t-runtime/rust-2.0"


def test_rust_runtime_denies_capability_like_reference(tmp_path:Path)->None:
    reference,productive=run_pair(tmp_path,{"confirmed":True,"hard_statuses":["PASS"],"cancelled":False},"")
    assert productive["observable"]==reference
    assert productive["observable"]["result"]["value"]=="CAPABILITY_DENIED:manifest"


def test_rust_runtime_rejects_tampered_tcap_before_execution(tmp_path:Path)->None:
    built=TcapV2Builder().build((ROOT/"examples/t-v2/owner_publish.t",),tmp_path/"publish.tcap",entry_module="owner.publish",entry_function="decide")
    (built.directory/"code.json").write_text("{}",encoding="utf-8")
    input_path=tmp_path/"input.json";input_path.write_text("{}",encoding="utf-8")
    completed=subprocess.run([str(RUNTIME),str(built.directory),"decide",str(input_path),"manifest"],capture_output=True,text=True,encoding="utf-8",timeout=15,check=False)
    assert completed.returncode==2
    assert "section hash" in completed.stderr
