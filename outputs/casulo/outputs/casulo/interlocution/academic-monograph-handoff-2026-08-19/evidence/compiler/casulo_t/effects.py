from __future__ import annotations

from .ast import EmitStmt, IfStmt, Statement


T_VNEXT_LANGUAGE = "T/1.1"
KNOWN_CAPABILITY_EFFECTS = frozenset(
    {
        "memory.read",
        "memory.write",
        "audio.capture",
        "audio.play",
        "model.infer",
        "network.connect",
        "filesystem.read",
        "filesystem.write",
        "process.spawn",
        "secret.read",
        "human.approval",
        "manifest",
        "catalog.read",
        "catalog.rebuild",
        "universe.inspect",
        "universe.warm",
        "universe.activate",
        "universe.quiesce",
        "universe.crystallize",
        "transition.execute",
        "index.query",
        "index.update",
        "blob.read",
        "blob.stage",
        "blob.publish",
        "gc.plan",
        "quantum.simulate",
        "quantum.qpu.submit",
    }
)


def derived_effects(body: tuple[Statement, ...]) -> tuple[str, ...]:
    """Fecha somente effects de capability; guard/control/evidence são internos."""

    effects: list[str] = []

    def visit(statements: tuple[Statement, ...]) -> None:
        for statement in statements:
            if isinstance(statement, EmitStmt) and "manifest" not in effects:
                effects.append("manifest")
            elif isinstance(statement, IfStmt):
                visit(statement.then_body)
                visit(statement.else_body)

    visit(body)
    return tuple(effects)
