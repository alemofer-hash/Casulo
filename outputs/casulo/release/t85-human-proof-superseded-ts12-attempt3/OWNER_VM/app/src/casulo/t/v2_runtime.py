from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Any, Mapping

from .authority import TDecisionReceipt, canonical_sha256


class V2RuntimeError(RuntimeError):
    pass


@dataclass(slots=True)
class _Control:
    steps: int
    max_steps: int
    deadline_ns: int

    def tick(self) -> None:
        self.steps += 1
        if self.steps > self.max_steps: raise V2RuntimeError("RESOURCE_STEPS_EXHAUSTED")
        if time.monotonic_ns() > self.deadline_ns: raise V2RuntimeError("DEADLINE_EXCEEDED")


@dataclass(frozen=True, slots=True)
class V2Execution:
    result: dict[str, Any]
    state_delta: dict[str, Any]
    requested_effects: tuple[str, ...]
    events: tuple[Any, ...]
    jobs: tuple[dict[str, Any], ...]
    diagnostics: tuple[str, ...]
    receipt: TDecisionReceipt

    def observable(self) -> dict[str, Any]:
        return {"result":self.result,"state_delta":self.state_delta,"requested_effects":list(self.requested_effects),"events":list(self.events),"jobs":list(self.jobs),"diagnostics":list(self.diagnostics)}


class V2ReferenceRuntime:
    runtime_id = "t-runtime/reference-2.0"

    def execute(self, ir: Mapping[str, Any], function_name: str, payload: Mapping[str, Any], *, grants: frozenset[str] = frozenset(), previous_receipt_hash: str = "0" * 64, source_hash: str = "0" * 64, tcap_hash: str = "0" * 64, scope_id: str = "scope:test", surface_id: str = "agent_behavior") -> V2Execution:
        function = next((item for item in ir["functions"] if item["name"] == function_name), None)
        if function is None: raise V2RuntimeError("FUNCTION_NOT_FOUND")
        state = {item["name"]:copy.deepcopy(item["initial"]) for item in ir["states"]}; initial = copy.deepcopy(state)
        environment: dict[str, Any] = {function["parameter"]["name"]:copy.deepcopy(dict(payload)),"state":state}
        control = _Control(0, int(ir["budgets"]["steps"]), time.monotonic_ns() + int(ir["budgets"]["deadline_ms"]) * 1_000_000)
        effects: list[str] = []; events: list[Any] = []; jobs: dict[str, dict[str, Any]] = {}; diagnostics: list[str] = []
        result = self._block(function["code"], environment, state, grants, effects, events, jobs, diagnostics, control)
        if result is None: raise V2RuntimeError("MISSING_RETURN")
        state_delta = {key:value for key,value in state.items() if initial.get(key) != value}
        observable = {"result":result,"state_delta":state_delta,"requested_effects":effects,"events":events,"jobs":list(jobs.values()),"diagnostics":diagnostics}
        receipt = TDecisionReceipt(
            decision_id=f"decision:{canonical_sha256(observable)[:24]}", surface_id=surface_id, scope_id=scope_id,
            t_source_hash=source_hash, t_ir_hash=canonical_sha256(ir), tcap_hash=tcap_hash,
            runtime_function=f"{ir['module']}::{function_name}", canonical_input_hash=canonical_sha256(payload), canonical_output_hash=canonical_sha256(observable),
            effects_requested=tuple(effects), grants_consumed=tuple(effect for effect in effects if effect in grants), foreign_calls=(), result=str(result.get("kind")), previous_receipt_hash=previous_receipt_hash,
            monotonic_timestamp_ns=time.monotonic_ns(), runtime_id=self.runtime_id,
        )
        return V2Execution(result,state_delta,tuple(effects),tuple(events),tuple(jobs.values()),tuple(diagnostics),receipt)

    def _block(self, code, env, state, grants, effects, events, jobs, diagnostics, control):
        for instruction in code:
            control.tick(); op=instruction["op"]
            if op == "require" or op == "ensure":
                if not self._eval(instruction["condition"],env,control): return {"kind":"error","value":copy.deepcopy(instruction["error"])}
            elif op == "cancel_if":
                if self._eval(instruction["value"],env,control): return {"kind":"error","value":"CANCELLED"}
            elif op == "let": env[instruction["name"]]=self._eval(instruction["value"],env,control)
            elif op == "set_state": state[instruction["name"]]=self._eval(instruction["value"],env,control)
            elif op == "request_effect":
                effect=instruction["effect"]
                if effect not in grants: return {"kind":"error","value":f"CAPABILITY_DENIED:{effect}"}
                effects.append(effect)
            elif op == "emit_event": events.append(self._eval(instruction["value"],env,control))
            elif op == "return_ok": return {"kind":"ok","value":self._eval(instruction["value"],env,control)}
            elif op == "return_error": return {"kind":"error","value":self._eval(instruction["value"],env,control)}
            elif op == "if":
                chosen=instruction["then"] if self._eval(instruction["condition"],env,control) else instruction["else"]
                result=self._block(chosen,env,state,grants,effects,events,jobs,diagnostics,control)
                if result is not None:return result
            elif op == "for":
                values=self._eval(instruction["iterable"],env,control)
                if not isinstance(values,list): raise V2RuntimeError("FOR_EXPECTED_LIST")
                if len(values)>instruction["limit"]: return {"kind":"error","value":"COLLECTION_BOUND_EXCEEDED"}
                for value in values:
                    nested=dict(env); nested[instruction["name"]]=value
                    result=self._block(instruction["body"],nested,state,grants,effects,events,jobs,diagnostics,control)
                    if result is not None:return result
            elif op == "spawn_job":
                name=instruction["name"]
                if name in jobs:return {"kind":"error","value":"JOB_ALREADY_EXISTS"}
                jobs[name]={"name":name,"status":"spawned","payload":self._eval(instruction["payload"],env,control),"limit":instruction["limit"]};env[name]=jobs[name]
            elif op == "join_job":
                if instruction["name"] not in jobs:return {"kind":"error","value":"JOB_NOT_FOUND"}
                jobs[instruction["name"]]["status"]="joined"
            elif op == "match":
                value=self._eval(instruction["value"],env,control); label=str(value).lower() if isinstance(value,bool) else str(value)
                case=next((item for item in instruction["cases"] if item["label"]==label),None) or next((item for item in instruction["cases"] if item["label"]=="_"),None)
                if case is None:raise V2RuntimeError("NON_EXHAUSTIVE_MATCH")
                result=self._block(case["body"],env,state,grants,effects,events,jobs,diagnostics,control)
                if result is not None:return result
            else: raise V2RuntimeError(f"UNKNOWN_OPCODE:{op}")
        return None

    def _eval(self,node,env,control):
        control.tick();op=node["op"]
        if op=="const":return copy.deepcopy(node["value"])
        if op=="name":return env[node["name"]]
        if op=="path":
            value=env[node["root"]]
            for part in node["path"]:value=value[part] if isinstance(value,dict) else getattr(value,part)
            return value
        if op=="not":return not self._eval(node["value"],env,control)
        if op in {"and","or"}:
            values=[bool(self._eval(item,env,control)) for item in node["values"]];return all(values) if op=="and" else any(values)
        if op in {"eq","ne","lt","le","gt","ge"}:
            left=self._eval(node["left"],env,control);right=self._eval(node["right"],env,control);return {"eq":left==right,"ne":left!=right,"lt":left<right,"le":left<=right,"gt":left>right,"ge":left>=right}[op]
        if op=="list":return [self._eval(item,env,control) for item in node["items"]]
        if op=="map":return {self._eval(k,env,control):self._eval(v,env,control) for k,v in node["items"]}
        if op=="call":
            args=[self._eval(item,env,control) for item in node["args"]];name=node["name"]
            if name=="len":return len(args[0])
            if name=="all_equal":return all(item==args[1] for item in args[0])
            if name=="contains":return args[1] in args[0]
            if name=="add":return args[0]+args[1]
            if name=="get":return args[0].get(args[1],args[2] if len(args)>2 else None)
        raise V2RuntimeError(f"UNKNOWN_EXPRESSION:{op}")
