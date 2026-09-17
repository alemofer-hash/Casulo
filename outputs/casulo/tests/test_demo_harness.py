from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from casulo.t.resource import ResourceContract, SemanticClass
from casulo.t.tcap import TcapSegment, build_tcap


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("casulo_demo_harness", ROOT / "release/demo_harness.py")
assert SPEC is not None and SPEC.loader is not None
HARNESS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HARNESS
SPEC.loader.exec_module(HARNESS)


def complete_serial(tcap_hash: str = "a" * 64) -> str:
    return "\n".join(
        (
            "G1_BOOT_SMOKE=PASS",
            "ARCH=x86_64",
            "TOPOLOGY_LOGICAL_CPUS=2",
            "TCAP_ARTIFACT=FloodSurrogate.tcap",
            "TCAP_VALIDATION=PASS",
            f"TCAP_HASH_SHA256={tcap_hash}",
            "RING3_PROCESSES=1",
            "PROCESS_SEPARATE_CR3=PASS",
            "FLOOD_SURROGATE_EXECUTION=PASS",
            "FLOOD_SURROGATE_EXIT_STATUS=0",
            "CONVENTIONAL_POLICY=PASS",
            "SEMANTIC_POLICY=PASS",
            "EQUIVALENCE_JUDGE=PASS",
            "SCHEDULER_TIMELINE=PASS",
            "FLOW_DISPATCHES=4",
            "ATTRACTOR_AUDIT_DISPATCHES=1",
            "NON_STARVATION=PASS",
            "AUDIT_STARVATION=0",
            "TCAP_CORRUPT_RESULT=QUARANTINE",
            "TCAP_CORRUPT_EXECUTED=0",
            "TIMING_STATUS=unavailable",
            "ENERGY_STATUS=unavailable",
            "CASULO_SHELL_SCOPE=bounded-read-only-parser/0.1",
            "CASULO_SHELL_SELF_TEST=PASS",
            "G7_DEMO_COMPLETE=PASS",
            "SHUTDOWN_PATH=isa-debug-exit/0.1",
            "REBOOT_PATH=8042-reset-probe-validated/0.1",
        )
    ) + "\n"


def test_complete_serial_contract_passes_parser() -> None:
    result = HARNESS.validate_serial(complete_serial(), tcap_sha256="a" * 64, returncode=33)
    assert result["pass"] is True
    assert [step["status"] for step in result["steps"]] == ["PASS"] * 10


def test_missing_marker_fails_closed() -> None:
    serial = complete_serial().replace("TCAP_CORRUPT_EXECUTED=0\n", "")
    result = HARNESS.validate_serial(serial, tcap_sha256="a" * 64, returncode=33)
    assert result["pass"] is False
    assert result["steps"][8]["status"] == "BLOCKED"


def test_wrong_tcap_hash_and_qemu_exit_fail_closed() -> None:
    result = HARNESS.validate_serial(complete_serial("b" * 64), tcap_sha256="a" * 64, returncode=0)
    assert result["pass"] is False
    assert result["steps"][1]["status"] == "BLOCKED"
    assert any("return code 33" in error for error in result["ordering_errors"])


def test_duplicate_or_out_of_order_markers_fail_closed() -> None:
    duplicated = complete_serial() + "G1_BOOT_SMOKE=PASS\n"
    assert HARNESS.validate_serial(duplicated, tcap_sha256="a" * 64, returncode=33)["pass"] is False
    out_of_order = complete_serial().replace("EQUIVALENCE_JUDGE=PASS\n", "").replace(
        "G7_DEMO_COMPLETE=PASS\n", "G7_DEMO_COMPLETE=PASS\nEQUIVALENCE_JUDGE=PASS\n"
    )
    assert HARNESS.validate_serial(out_of_order, tcap_sha256="a" * 64, returncode=33)["pass"] is False


def test_measurements_before_equivalence_fail_closed() -> None:
    lines = complete_serial().splitlines()
    lines.remove("ENERGY_STATUS=unavailable")
    lines.insert(lines.index("EQUIVALENCE_JUDGE=PASS"), "ENERGY_STATUS=unavailable")
    result = HARNESS.validate_serial("\n".join(lines), tcap_sha256="a" * 64, returncode=33)
    assert result["pass"] is False
    assert any("before equivalence" in error for error in result["ordering_errors"])


def test_missing_validated_reboot_path_fails_closed() -> None:
    serial = complete_serial().replace(
        "REBOOT_PATH=8042-reset-probe-validated/0.1\n", ""
    )
    result = HARNESS.validate_serial(
        serial, tcap_sha256="a" * 64, returncode=33
    )

    assert result["pass"] is False
    assert result["steps"][9]["status"] == "BLOCKED"


def test_synthetic_fixture_can_never_satisfy_g7(tmp_path: Path) -> None:
    summary = HARNESS.run_rehearsal(
        image=tmp_path / "missing.img",
        tcap=tmp_path / "missing.tcap",
        manifest=tmp_path / "missing.json",
        repeat=10,
        timeout=1,
        serial_fixture=complete_serial(),
    )
    assert summary["evidence_kind"] == "synthetic_parser_test"
    assert summary["synthetic_evidence_can_satisfy_g7"] is False
    assert summary["g7_pass"] is False
    assert summary["status"] == "BLOCKED"


def test_host_tcap_check_validates_original_and_rejects_controlled_corruption(tmp_path: Path) -> None:
    contract = ResourceContract(
        memory_limit_bytes=4096,
        arena_bytes=4096,
        max_threads=1,
        semantic_class=SemanticClass.FLOW,
        deterministic=True,
        numerical_precision="float32",
        permissions=("console",),
        quality_definition={"protocol": "casulo-equivalence/1", "max_abs": 0.0},
        residual_routing={"invalid": "QUARANTINE"},
    )
    raw = build_tcap(
        segments=(TcapSegment("text", b"\xc3", "rx"),),
        target="x86_64-unknown-none",
        abi="casulo-syscall/0.1",
        entry_segment="text",
        entry_offset=0,
        compiler={"name": "test", "version": "0", "commit": "test-only"},
        resource_contract=contract,
    )
    artifact = tmp_path / "FloodSurrogate.tcap"
    artifact.write_bytes(raw)
    result = HARNESS.verify_tcap(artifact)
    assert result["status"] == "PASS"
    assert result["valid_original"] is True
    assert result["corruption_rejected"] is True


def test_release_manifest_requires_matching_image_and_tcap(tmp_path: Path) -> None:
    image = tmp_path / "image.img"
    tcap = tmp_path / "FloodSurrogate.tcap"
    image.write_bytes(b"image")
    tcap.write_bytes(b"tcap")
    manifest = tmp_path / "RELEASE_MANIFEST.json"
    image_key = image.relative_to(ROOT).as_posix() if image.is_relative_to(ROOT) else str(image)
    tcap_key = tcap.relative_to(ROOT).as_posix() if tcap.is_relative_to(ROOT) else str(tcap)
    manifest.write_text(
        json.dumps(
            {
                "schema": "casulo-so-release-manifest/0.1",
                "physical_device_written": False,
                "publication_performed": False,
                "artifacts": [
                    {"path": image_key, "bytes": image.stat().st_size, "sha256": HARNESS.sha256(image)},
                    {"path": tcap_key, "bytes": tcap.stat().st_size, "sha256": HARNESS.sha256(tcap)},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert HARNESS.verify_release_manifest(manifest, image, tcap)["status"] == "PASS"
    image.write_bytes(b"changed")
    assert HARNESS.verify_release_manifest(manifest, image, tcap)["status"] == "BLOCKED"
