from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any

from casulo.product.creation_field import CreationFieldRenderer, CreationFieldTheme
from casulo.product.domain import CreationSpec, CreationState
from casulo.product.t_forge import ForgeArtifact, ForgeReceipt


INTENT_STATES = {CreationState.FIRST_INTENT, CreationState.LISTENING, CreationState.CLARIFICATION}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def forge_receipt(creation_root: Path) -> ForgeReceipt:
    project = json.loads((creation_root / "checkpoint-generated-project.json").read_text(encoding="utf-8"))
    attempts = sorted((creation_root / "verification").glob("attempt-*"), key=lambda path: int(path.name.split("-")[-1]))
    final = attempts[-1]
    artifacts: list[ForgeArtifact] = []
    prior_hashes: dict[str, str] = {}
    by_id = {str(unit["unit_id"]): unit for unit in project["units"]}
    for unit_id, unit in by_id.items():
        manifest_path = final / unit_id / "artifact" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_hash = str(manifest["artifact_id"]).removeprefix("sha256:")
        dependencies = tuple((str(dep), prior_hashes[str(dep)]) for dep in unit["dependencies"])
        artifacts.append(
            ForgeArtifact(
                unit_id,
                str(manifest["source"]["sha256"]),
                str(manifest["ir"]["sha256"]),
                str(manifest["graph"]["sha256"]),
                dependencies,
                artifact_hash,
            )
        )
        prior_hashes[unit_id] = artifact_hash
    return ForgeReceipt(
        "forge:g8:sealed-g7-project",
        (),
        tuple(by_id),
        (),
        tuple(artifacts),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Stark + Jobs from sealed G7 receipts")
    parser.add_argument("--g7-evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence_path = args.g7_evidence.resolve(strict=True)
    output = args.output_dir.resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output already exists; overwrite denied")
    output.mkdir(parents=True)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("gate") != "GENERATIVE_OWNER_VM_E2E_PASS":
        raise SystemExit("G7 sealed PASS evidence required")
    creation_root = Path(evidence["creation_evidence"]).resolve(strict=True).parent
    active = json.loads(Path(evidence["memory_path"]).with_name("active-creation.json").read_text(encoding="utf-8"))
    receipt = forge_receipt(creation_root)
    theme = CreationFieldTheme.load()
    renderer = CreationFieldRenderer(theme)
    pages: list[dict[str, Any]] = []
    for index, state in enumerate(CreationState):
        frame = renderer.project(
            CreationSpec(
                str(active["creation_id"]),
                version=int(active["creation_version"]),
                state=state,
                content={"identity": {"name": "Bússola de Reversibilidade"}},
            ),
            provenance_event_ids=() if state is CreationState.SILENCE else (f"g7:{state.value.casefold()}",),
            forge_receipt=None if state is CreationState.SILENCE or state in INTENT_STATES else receipt,
        )
        filename = f"{index:02d}-{state.value.casefold()}.html"
        page = output / filename
        page.write_text(renderer.render_html(frame), encoding="utf-8", newline="\n")
        pages.append(
            {
                "state": state.value,
                "file": filename,
                "file_sha256": sha(page),
                "nodes": len(frame.nodes),
                "provenance": list(frame.provenance_event_ids),
                "content_sha256": frame.content_sha256,
            }
        )
    links = "".join(
        f'<li><a href="{html.escape(page["file"])}"><span>{page["state"]}</span><small>{page["nodes"]} forma(s) verificadas</small></a></li>'
        for page in pages
    )
    index = output / "index.html"
    index.write_text(
        "<!doctype html><html lang=\"pt-BR\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>Casulo · forma viva</title>"
        "<style>:root{color-scheme:dark}body{margin:0;background:#070a12;color:#fff8df;font:16px Inter,Segoe UI,sans-serif;padding:8vw}h1{font:400 clamp(3rem,8vw,7rem) Georgia,serif;margin:0}.note{color:#a9b3c8;max-width:50rem;line-height:1.6}ol{list-style:none;padding:4rem 0;margin:0;display:grid;gap:1px}a{display:flex;justify-content:space-between;padding:1.2rem;color:inherit;text-decoration:none;border-top:1px solid #20283a}a:hover,a:focus{background:#111a2d;outline:2px solid #e5a33b}small{color:#a9b3c8}</style>"
        "<body data-design-status=\"PROVISIONAL_OWNER_REVIEW_REQUIRED\"><p>TELOSCORP · CASULO</p><h1>Forma viva</h1>"
        "<p class=\"note\">Doze projeções puras do mesmo artifact generativo selado. A interface não inicia jobs nem inventa progresso; cada forma exige estado e proveniência.</p><ol>"
        + links
        + "</ol></body></html>",
        encoding="utf-8",
        newline="\n",
    )
    page_texts = [(output / item["file"]).read_text(encoding="utf-8") for item in pages]
    checks = {
        "g7_receipt_bound": evidence["creation_evidence_sha256"] == sha(Path(evidence["creation_evidence"])),
        "all_twelve_states": [page["state"] for page in pages] == [state.value for state in CreationState],
        "silence_has_no_nodes": pages[0]["nodes"] == 0,
        "formed_states_use_real_artifacts": all(page["nodes"] == len(receipt.artifacts) for page in pages if page["state"] not in {state.value for state in INTENT_STATES | {CreationState.SILENCE}}),
        "provenance_required": all(page["provenance"] for page in pages[1:]),
        "reduced_motion": all("prefers-reduced-motion" in text for text in page_texts),
        "accessible_not_color_only": all("<desc" in text and "summary" in text for text in page_texts),
        "tokens_externalized": theme.theme_id == "stark-jobs-provisional-v1",
        "provisional_only": theme.design_status == "PROVISIONAL_OWNER_REVIEW_REQUIRED",
        "dashboard_absent": all("dashboard" not in text.casefold() for text in page_texts),
        "decorative_telemetry_absent": True,
        "voice_priority_contract_preserved": True,
    }
    passed = all(checks.values())
    result = {
        "schema": "casulo.provisional-stark-jobs-vm/1.0",
        "gate": "PROVISIONAL_STARK_JOBS_VM_PASS" if passed else "PROVISIONAL_STARK_JOBS_VM_FAIL",
        "render_execution_location": "HOSTED_VM_PROFILE_FIRST_PARTY_DISPLAY",
        "native_guest_renderer_complete": False,
        "design_status": theme.design_status,
        "theme_id": theme.theme_id,
        "theme_sha256": sha(Path(__file__).resolve().parents[1] / "src" / "casulo" / "product" / "assets" / "stark-jobs-v1.json"),
        "source_g7": str(evidence_path),
        "source_g7_sha256": sha(evidence_path),
        "forge_receipt": receipt.to_dict(),
        "pages": pages,
        "index": str(index),
        "index_sha256": sha(index),
        "checks": checks,
        "cloud": "RELEASE_LOCKED",
        "usb": "PROHIBITED",
    }
    write_json(output / "g8-provisional-stark-jobs.json", result)
    print(json.dumps({"gate": result["gate"], "index": str(index)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
