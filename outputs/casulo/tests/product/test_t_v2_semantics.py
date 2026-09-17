from __future__ import annotations

import json
from pathlib import Path

import pytest

from casulo.t.v2_parser import V2ParseError, V2Parser, parse_type
from casulo.t.v2_semantics import V2Analyzer


ROOT = Path(__file__).resolve().parents[2]


SOURCE = '''language T/2.0
module owner.publish
budget steps 4096
budget deadline_ms 5000
schema version 1
capability manifest

record PublishInput
  member confirmed: Bool
  member hard_statuses: List<Text,64>
  member cancelled: Bool

enum PublishDecision
  case PUBLISH
  case BLOCKED

state attempts: Int = 0

fn decide(input: PublishInput) -> Result<Text,Text>
  effects [manifest]
  cancel if input.cancelled
  requires input.confirmed else "intent_unconfirmed"
  for status in input.hard_statuses limit 64
    requires status == "PASS" else "hard_requirement_not_pass"
  set state.attempts = add(state.attempts, 1)
  spawn job audit using input.hard_statuses limit 64
  join job audit
  request effect manifest
  if input.confirmed
    return ok "PUBLISH"
  else
    return error "BLOCKED"
'''


def test_t_v2_parses_records_enums_result_collections_state_and_bounded_control() -> None:
    module = V2Parser().parse(SOURCE, "publish.t")
    result = V2Analyzer().analyze(module)
    assert result.ok, result.diagnostics
    assert module.step_budget == 4096
    assert module.deadline_ms == 5000
    assert module.schema_version == 1
    assert module.records[0].members[1].type_ref.bound == 64
    assert module.functions[0].return_type.name == "Result"
    assert any(item.kind == "for" for item in module.functions[0].body)


def test_t_v2_rejects_unbounded_collection() -> None:
    with pytest.raises(V2ParseError):
        parse_type("List<Text>", V2Parser().parse(SOURCE).records[0].span)


def test_t_v2_rejects_effect_without_capability() -> None:
    module = V2Parser().parse(SOURCE.replace("capability manifest", "capability memory.read"))
    result = V2Analyzer().analyze(module)
    assert "T2107" in {item.code for item in result.diagnostics}


def test_t_v2_rejects_unbounded_or_forbidden_expression_call() -> None:
    source = SOURCE.replace('requires input.confirmed else "intent_unconfirmed"', 'requires open("secret") else "bad"')
    result = V2Analyzer().analyze(V2Parser().parse(source))
    assert "T2117" in {item.code for item in result.diagnostics}


def test_t_v2_requires_return_on_all_reachable_fallthroughs() -> None:
    source = SOURCE.replace('  else\n    return error "BLOCKED"\n', '')
    result = V2Analyzer().analyze(V2Parser().parse(source))
    assert "T2109" in {item.code for item in result.diagnostics}


def test_t_v2_rejects_non_json_state_and_odd_indent() -> None:
    with pytest.raises(V2ParseError):
        V2Parser().parse(SOURCE.replace("state attempts: Int = 0", "state attempts: Int = nope"))
    with pytest.raises(V2ParseError):
        V2Parser().parse(SOURCE.replace("  member confirmed", " member confirmed"))


def test_t_v2_rejects_unknown_types_and_duplicate_members() -> None:
    source = SOURCE.replace("member cancelled: Bool", "member confirmed: Mystery")
    result = V2Analyzer().analyze(V2Parser().parse(source))
    codes = {item.code for item in result.diagnostics}
    assert {"T2102", "T2118"} <= codes


def test_t_v2_match_requires_exhaustive_fallback() -> None:
    match_source = SOURCE.replace(
        '  if input.confirmed\n    return ok "PUBLISH"\n  else\n    return error "BLOCKED"',
        '  match input.confirmed\n    case true\n      return ok "PUBLISH"\n    case _\n      return error "BLOCKED"',
    )
    result = V2Analyzer().analyze(V2Parser().parse(match_source))
    assert result.ok, result.diagnostics
    incomplete = match_source.replace('    case _\n      return error "BLOCKED"\n', '')
    result = V2Analyzer().analyze(V2Parser().parse(incomplete))
    assert "T2122" in {item.code for item in result.diagnostics}


def test_t_v2_owner_publish_golden_summary() -> None:
    module = V2Parser().parse_path(ROOT / "examples/t-v2/owner_publish.t")
    actual = {
        "capabilities": list(module.capabilities),
        "deadline_ms": module.deadline_ms,
        "enums": {item.name: list(item.cases) for item in module.enums},
        "functions": {item.name: {"effects": list(item.effects), "return": item.return_type.name} for item in module.functions},
        "module": module.name,
        "records": {item.name: [member.name for member in item.members] for item in module.records},
        "schema_version": module.schema_version,
        "states": [item.name for item in module.states],
        "step_budget": module.step_budget,
    }
    expected = json.loads((ROOT / "tests/golden/t-v2/owner_publish.summary.json").read_text(encoding="utf-8"))
    assert actual == expected
