from __future__ import annotations

import hashlib
import html
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain import CreationSpec, CreationState, IntentDelta, canonical_sha256
from .platform_contracts import PlatformError
from .t_forge import ForgeReceipt


_COLORS = {
    CreationState.SILENCE: ("ivory", "quiet"),
    CreationState.FIRST_INTENT: ("amber", "proposed"),
    CreationState.LISTENING: ("amber", "listening"),
    CreationState.FIRST_FORM: ("cobalt", "formed"),
    CreationState.CLARIFICATION: ("amber", "clarification"),
    CreationState.CONFIRMATION: ("cobalt", "confirmation"),
    CreationState.PERSONALITY: ("cobalt", "personality"),
    CreationState.SIMULATION: ("cobalt", "simulation"),
    CreationState.INTERRUPTION: ("amber", "interruption"),
    CreationState.CORRECTION: ("amber", "correction"),
    CreationState.AGREEMENT: ("ivory", "agreement"),
    CreationState.MATERIALIZATION: ("cobalt", "materialization"),
}

_INTENT_STATES = {
    CreationState.FIRST_INTENT,
    CreationState.LISTENING,
    CreationState.CLARIFICATION,
}

_SUMMARIES = {
    CreationState.SILENCE: "O campo está em silêncio, disponível sem fingir atividade.",
    CreationState.FIRST_INTENT: "Uma intencao apareceu; sua forma ainda e provisoria.",
    CreationState.LISTENING: "O Guia continua ouvindo; nada novo foi confirmado.",
    CreationState.FIRST_FORM: "A primeira forma esta visivel e ainda pode ser corrigida.",
    CreationState.CLARIFICATION: "Uma ambiguidade material precisa de esclarecimento.",
    CreationState.CONFIRMATION: "A forma aguarda confirmacao consciente antes de seguir.",
    CreationState.PERSONALITY: "A personalidade esta explicita sem alterar permissoes.",
    CreationState.SIMULATION: "A criacao esta em simulacao, sem efeitos reais.",
    CreationState.INTERRUPTION: "A manifestacao foi interrompida; o estado foi preservado.",
    CreationState.CORRECTION: "A correcao local destaca somente o subgrafo afetado.",
    CreationState.AGREEMENT: "O acordo esta selado e pronto para materializacao.",
    CreationState.MATERIALIZATION: "O pacote esta sendo manifestado a partir de receipts reais.",
}


@dataclass(frozen=True, slots=True)
class CreationFieldTheme:
    theme_id: str
    design_status: str
    colors: dict[str, str]

    @classmethod
    def load(cls, path: str | Path | None = None) -> "CreationFieldTheme":
        source = Path(path) if path is not None else Path(__file__).with_name("assets") / "stark-jobs-v1.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        if payload.get("schema") != "casulo.creation-field-theme/1.0":
            raise PlatformError("schema visual invalido")
        colors = payload.get("colors")
        required = {"ink", "ivory", "amber", "cobalt", "mist", "deep_blue"}
        if not isinstance(colors, dict) or set(colors) != required:
            raise PlatformError("tokens de cor incompletos")
        if any(not isinstance(value, str) or not value.startswith("#") for value in colors.values()):
            raise PlatformError("token de cor invalido")
        status = str(payload.get("design_status", ""))
        if status != "PROVISIONAL_OWNER_REVIEW_REQUIRED":
            raise PlatformError("tema nao pode alegar aprovacao final")
        return cls(str(payload.get("theme_id", "")), status, dict(colors))

    @property
    def css_tokens(self) -> str:
        return ":root{" + ";".join(f"--{key.replace('_', '-')}:{value}" for key, value in self.colors.items()) + "}"


@dataclass(frozen=True, slots=True)
class FieldNode:
    node_id: str
    label: str
    kind: str
    x: float
    y: float
    radius: float
    semantic_color: str
    certainty: str
    source_ids: tuple[str, ...]
    artifact_sha256: str | None
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "radius": self.radius,
            "semantic_color": self.semantic_color,
            "certainty": self.certainty,
            "source_ids": list(self.source_ids),
            "artifact_sha256": self.artifact_sha256,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class CreationFieldFrame:
    creation_id: str
    version: int
    state: CreationState
    semantic_color: str
    phase: str
    summary: str
    nodes: tuple[FieldNode, ...]
    edges: tuple[tuple[str, str], ...]
    provenance_event_ids: tuple[str, ...]
    confirmation_ring: bool
    content_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "casulo.creation-field/1.0",
            "creation_id": self.creation_id,
            "version": self.version,
            "state": self.state.value,
            "semantic_color": self.semantic_color,
            "phase": self.phase,
            "summary": self.summary,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [list(edge) for edge in self.edges],
            "provenance_event_ids": list(self.provenance_event_ids),
            "confirmation_ring": self.confirmation_ring,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class CreationPresentation:
    """Validated, total projection used by human-facing renderers."""

    creation: CreationSpec
    display_name: str
    identity_source: str
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_creation(cls, creation: CreationSpec) -> "CreationPresentation":
        diagnostics: list[str] = []
        display_name: str | None = None
        identity_source = "creation_id"
        content = creation.content
        identity = content.get("identity")
        if identity is not None and not isinstance(identity, dict):
            raise PlatformError("identity precisa ser objeto")
        elif isinstance(identity, dict):
            name = identity.get("name")
            if isinstance(name, str) and name.strip():
                display_name, identity_source = name.strip(), "identity.name"
            elif isinstance(name, dict):
                value = name.get("value")
                if isinstance(value, str) and value.strip():
                    display_name, identity_source = value.strip(), "identity.name.value"
                elif "value" in name:
                    raise PlatformError("identity.name.value precisa ser texto")
                else:
                    diagnostics.append("identity_name_value_missing")
            elif name is not None:
                raise PlatformError("identity.name precisa ser texto ou objeto")
            else:
                diagnostics.append("identity_name_missing")
        else:
            diagnostics.append("identity_missing")
        if display_name is None:
            legacy_name = content.get("name")
            if isinstance(legacy_name, str) and legacy_name.strip():
                display_name, identity_source = legacy_name.strip(), "content.name"
        if display_name is None:
            display_name = creation.creation_id
        return cls(creation, display_name, identity_source, tuple(diagnostics))


class CreationFieldRenderer:
    """Pure projection. It cannot start work, grant effects, or invent progress."""

    def __init__(self, theme: CreationFieldTheme | None = None) -> None:
        self.theme = theme or CreationFieldTheme.load()

    def project(
        self,
        creation: CreationSpec,
        *,
        provenance_event_ids: tuple[str, ...],
        forge_receipt: ForgeReceipt | None = None,
        pending_delta: IntentDelta | None = None,
    ) -> CreationFieldFrame:
        if creation.state is not CreationState.SILENCE and not provenance_event_ids:
            raise PlatformError("Campo não pode manifestar estado sem proveniência")
        semantic_color, phase = _COLORS[creation.state]
        nodes: list[FieldNode] = []
        edges: list[tuple[str, str]] = []
        if creation.state is CreationState.SILENCE:
            summary = _SUMMARIES[creation.state]
        elif creation.state in _INTENT_STATES:
            summary = _SUMMARIES[creation.state]
            nodes.append(self._intent_node(pending_delta, provenance_event_ids))
        else:
            if forge_receipt is None:
                raise PlatformError("estado formado exige receipt real do Forge")
            artifact_by_id = {artifact.unit_id: artifact for artifact in forge_receipt.artifacts}
            for unit_id in sorted(artifact_by_id):
                artifact = artifact_by_id[unit_id]
                x, y = _position(unit_id)
                fingerprint = canonical_sha256(
                    {
                        "node_id": unit_id,
                        "artifact_sha256": artifact.artifact_sha256,
                        "x": x,
                        "y": y,
                    }
                )
                nodes.append(
                    FieldNode(
                        node_id=unit_id,
                        label=unit_id.replace("_", " ").title(),
                        kind="forge-unit",
                        x=x,
                        y=y,
                        radius=46.0 if unit_id == "interface" else 38.0,
                        semantic_color="cobalt" if unit_id in forge_receipt.rebuilt_units else "ivory",
                        certainty="confirmed",
                        source_ids=provenance_event_ids,
                        artifact_sha256=artifact.artifact_sha256,
                        fingerprint=fingerprint,
                    )
                )
                for dependency, _digest in artifact.dependency_artifact_sha256:
                    edges.append((dependency, unit_id))
            summary = _SUMMARIES[creation.state]
        return CreationFieldFrame(
            creation_id=creation.creation_id,
            version=creation.version,
            state=creation.state,
            semantic_color=semantic_color,
            phase=phase,
            summary=summary,
            nodes=tuple(nodes),
            edges=tuple(sorted(set(edges))),
            provenance_event_ids=provenance_event_ids,
            confirmation_ring=creation.state in {CreationState.CONFIRMATION, CreationState.AGREEMENT},
            content_sha256=creation.sha256,
        )

    def render_html(self, frame: CreationFieldFrame) -> str:
        node_by_id = {node.node_id: node for node in frame.nodes}
        edge_markup = "".join(
            _edge_svg(node_by_id[source], node_by_id[target])
            for source, target in frame.edges
            if source in node_by_id and target in node_by_id
        )
        node_markup = "".join(_node_svg(node) for node in frame.nodes)
        ring = (
            '<circle class="confirmation-ring" cx="500" cy="318" r="244" />'
            if frame.confirmation_ring
            else ""
        )
        summary = html.escape(frame.summary)
        state = html.escape(frame.state.value)
        creation_id = html.escape(frame.creation_id)
        provenance = html.escape(", ".join(frame.provenance_event_ids) or "nenhuma")
        data = html.escape(json.dumps(frame.to_dict(), ensure_ascii=False, sort_keys=True))
        return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
  <title>Casulo · {state}</title>
  <style>{self.theme.css_tokens}{_CSS}</style>
</head>
<body class="state-{state.casefold()}" data-theme="{html.escape(self.theme.theme_id)}" data-design-status="{self.theme.design_status}">
  <main aria-labelledby="field-title" data-frame="{data}">
    <header>
      <p class="eyebrow">TELOSCORP · CASULO</p>
      <h1 id="field-title">{state.replace('_', ' ')}</h1>
      <p class="summary">{summary}</p>
    </header>
    <section class="field" aria-label="Campo da criação {creation_id}">
      <svg viewBox="0 0 1000 640" role="img" aria-labelledby="svg-title svg-desc">
        <title id="svg-title">Forma atual da criação</title>
        <desc id="svg-desc">Estado {state}, versão {frame.version}, com {len(frame.nodes)} manifestações verificadas.</desc>
        <defs>
          <filter id="glow"><feGaussianBlur stdDeviation="8" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <radialGradient id="core"><stop offset="0" stop-color="#fff8df"/><stop offset=".55" stop-color="#e5a33b" stop-opacity=".72"/><stop offset="1" stop-color="#17243c" stop-opacity="0"/></radialGradient>
        </defs>
        <ellipse class="breath" cx="500" cy="320" rx="165" ry="118" />
        {ring}{edge_markup}{node_markup}
      </svg>
    </section>
    <footer>
      <span>{creation_id} · v{frame.version}</span>
      <span>proveniência: {provenance}</span>
    </footer>
  </main>
</body>
</html>
"""

    @staticmethod
    def _intent_node(
        delta: IntentDelta | None,
        provenance_event_ids: tuple[str, ...],
    ) -> FieldNode:
        label = "Primeira intenção"
        artifact = None
        source_ids = provenance_event_ids
        if delta is not None:
            label = " · ".join(".".join(path) for path in delta.affected_paths)
            artifact = canonical_sha256(delta.to_dict())
            source_ids = delta.source_event_ids
        fingerprint = canonical_sha256(
            {"kind": "intent-seed", "label": label, "artifact": artifact}
        )
        return FieldNode(
            node_id="intent-seed",
            label=label,
            kind="intent-seed",
            x=500,
            y=320,
            radius=34,
            semantic_color="amber",
            certainty="proposed",
            source_ids=source_ids,
            artifact_sha256=artifact,
            fingerprint=fingerprint,
        )


def _position(unit_id: str) -> tuple[float, float]:
    digest = hashlib.sha256(unit_id.encode("utf-8")).digest()
    angle = int.from_bytes(digest[:2], "big") / 65535 * math.tau
    distance = 128 + digest[2] / 255 * 92
    return round(500 + math.cos(angle) * distance, 3), round(320 + math.sin(angle) * distance * 0.72, 3)


def _edge_svg(source: FieldNode, target: FieldNode) -> str:
    return (
        f'<path class="filament" d="M {source.x} {source.y} '
        f'Q 500 320 {target.x} {target.y}" />'
    )


def _node_svg(node: FieldNode) -> str:
    label = html.escape(node.label)
    return (
        f'<g class="manifestation color-{node.semantic_color}" data-node="{html.escape(node.node_id)}" '
        f'data-fingerprint="{node.fingerprint}">'
        f'<circle cx="{node.x}" cy="{node.y}" r="{node.radius}" />'
        f'<text x="{node.x}" y="{node.y + node.radius + 24}" text-anchor="middle">{label}</text>'
        "</g>"
    )


_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 50% 42%,var(--deep-blue) 0,#0b1020 38%,var(--ink) 76%);color:var(--ivory);font-family:Inter,Segoe UI,sans-serif}
main{min-height:100vh;display:grid;grid-template-rows:auto 1fr auto;padding:clamp(24px,5vw,72px)}header{max-width:760px;position:relative;z-index:2}.eyebrow{color:var(--amber);font-size:.72rem;letter-spacing:.28em;margin:0 0 18px}h1{font-family:Georgia,serif;font-weight:400;font-size:clamp(2.5rem,7vw,6.4rem);letter-spacing:-.045em;margin:0}.summary{max-width:620px;color:var(--mist);font-size:clamp(1rem,2vw,1.25rem);line-height:1.55}.field{min-height:420px;display:grid;place-items:center}svg{width:min(100%,1100px);overflow:visible}.breath{fill:url(#core);opacity:.42;transform-origin:center;animation:breathe 6s ease-in-out infinite}.filament{fill:none;stroke:var(--cobalt);stroke-width:2;stroke-opacity:.42}.confirmation-ring{fill:none;stroke:var(--amber);stroke-width:2;stroke-dasharray:5 12;filter:url(#glow)}.manifestation circle{fill:#111a2d;stroke-width:2;filter:url(#glow)}.color-cobalt circle{stroke:var(--cobalt)}.color-ivory circle{stroke:var(--ivory)}.color-amber circle{stroke:var(--amber)}.manifestation text{fill:var(--ivory);font-size:14px;letter-spacing:.06em}footer{display:flex;gap:24px;justify-content:space-between;color:#73809b;font:12px ui-monospace,monospace;border-top:1px solid #20283a;padding-top:16px}@keyframes breathe{50%{transform:scale(1.04);opacity:.62}}@media(max-width:700px){footer{flex-direction:column;gap:6px}.field{min-height:360px}}@media(prefers-reduced-motion:reduce){*{animation:none!important}}
"""
