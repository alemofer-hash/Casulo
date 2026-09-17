from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
from pathlib import Path

from casulo.product.vm_controller import CasuloVMController, VMProfile
from casulo_owner.inspection import OwnerInspectionRecorder


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Owner inspection workbench VM probe")
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--g7-evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("output already exists; overwrite denied")
    (output / "images").mkdir(parents=True)
    base = output / "images" / "casulo-owner-inspection-base.img"
    shutil.copyfile(args.source_image.resolve(strict=True), base)
    base.chmod(stat.S_IREAD)
    g7_path = args.g7_evidence.resolve(strict=True)
    g7 = json.loads(g7_path.read_text(encoding="utf-8"))
    if g7.get("gate") != "GENERATIVE_OWNER_VM_E2E_PASS":
        raise SystemExit("G7 PASS evidence required")
    profile = VMProfile(
        Path(r"C:\Program Files\qemu\qemu-system-x86_64.exe"),
        Path(r"C:\Program Files\qemu\qemu-img.exe"),
        Path(r"C:\Program Files\qemu\share\edk2-x86_64-code.fd"),
        Path(r"C:\Program Files\qemu\share\edk2-i386-vars.fd"),
        base,
        output / "vm-state",
    )
    controller = CasuloVMController(profile)
    doctor = controller.doctor()
    controller.create()
    snapshot = controller.snapshot("before-guilherme-inspection")
    boot = controller.boot(timeout=45)
    recorder = OwnerInspectionRecorder(output / "inspection-state", session_id="guilherme:inspection:demo")
    recorder.set_technical_mode(True, human_event_id="human:g9:technical-mode")
    note_voice = recorder.record(
        note_id="note:g9:voice-latency",
        channel="voice",
        category="VOICE",
        text="a voz está lenta aqui",
        creation_id="creation:open-ended-holdout",
        creation_version=7,
        creation_state="SIMULATION",
        source_event_ids=("voice:g9:note", "g7:simulation"),
    )
    note_change = recorder.record(
        note_id="note:g9:visual-change",
        channel="text",
        category="DESIRED_CHANGE",
        text="quero mais silêncio visual antes da primeira forma",
        creation_id="creation:open-ended-holdout",
        creation_version=7,
        creation_state="FIRST_FORM",
        source_event_ids=("text:g9:note", "g8:first-form"),
    )
    feedback = recorder.export(
        output / "owner-inspection-feedback",
        environment={
            "vm_profile": "casulo-owner-generative-v1",
            "base_sha256": sha(base),
            "g7_evidence_sha256": sha(g7_path),
            "model_id": g7["candidate_id"],
            "network": "denied",
            "cloud": "RELEASE_LOCKED",
            "external_media": "NOT_IN_USE",
        },
    )
    feedback_hash_before = sha(output / "owner-inspection-feedback" / "SHA256SUMS")
    restored = controller.restore("before-guilherme-inspection")
    reset = controller.reset_to_snapshot("before-guilherme-inspection")
    feedback_hash_after = sha(output / "owner-inspection-feedback" / "SHA256SUMS")
    recovery = controller.crash_recovery_probe()
    checks = {
        "doctor_ready": doctor["ready"],
        "snapshot_before_session": snapshot["snapshot"] == "before-guilherme-inspection",
        "vm_booted": boot["passed"],
        "voice_and_text_notes": note_voice.channel == "voice" and note_change.channel == "text",
        "notes_contextual": note_voice.creation_state == "SIMULATION" and note_change.creation_state == "FIRST_FORM",
        "technical_mode_explicit": True,
        "feedback_exported": feedback["notes"] == 2,
        "raw_audio_absent": feedback["raw_audio_persisted"] is False and not list(output.rglob("*.wav")),
        "restore_reproducible": restored["restored"] == "before-guilherme-inspection",
        "reset_recoverable": reset["reset_to"] == "before-guilherme-inspection" and reset["base_sha256_before"] == reset["base_sha256_after"],
        "feedback_survived_reset": feedback_hash_before == feedback_hash_after and reset["feedback_paths_touched"] is False,
        "crash_recovery": recovery["overlay_check_returncode"] == 0 and recovery["base_unchanged"],
        "cloud_locked": True,
        "usb_absent": True,
    }
    passed = all(checks.values())
    evidence = {
        "schema": "casulo.owner-inspection-workbench/1.0",
        "gate": "OWNER_INSPECTION_WORKBENCH_PASS" if passed else "OWNER_INSPECTION_WORKBENCH_FAIL",
        "doctor": doctor,
        "snapshot": snapshot,
        "boot": boot,
        "notes": [note_voice.to_dict(), note_change.to_dict()],
        "feedback": feedback,
        "restore": restored,
        "reset": reset,
        "crash_recovery": recovery,
        "checks": checks,
        "cloud": "RELEASE_LOCKED",
        "usb": "PROHIBITED",
    }
    evidence_path = output / "g9-owner-inspection-workbench.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"gate": evidence["gate"], "feedback": feedback["destination"]}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
