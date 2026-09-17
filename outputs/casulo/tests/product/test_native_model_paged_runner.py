from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "os/tools/run_native_model_paged_qemu.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("native_model_paged_runner", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_paged_runner_command_is_bounded_read_only_and_networkless() -> None:
    runner = load_runner()
    command = runner.build_command(
        Path("qemu-system-x86_64"),
        Path("OVMF_CODE.fd"),
        Path("OVMF_VARS.fd"),
        Path("casulo.img"),
        Path("model.gguf"),
    )
    joined = " ".join(str(item) for item in command)
    assert "-nic none" in joined
    assert "readonly=on,file=casulo.img" in joined
    assert "name=opt/com.teloscorp.casulo/model.gguf,file=model.gguf" in joined
    assert "PhysicalDrive" not in joined
    assert "-net" not in command


def test_paged_runner_exposes_only_frozen_memory_profiles() -> None:
    runner = load_runner()
    command = runner.build_command(
        Path("qemu-system-x86_64"),
        Path("OVMF_CODE.fd"),
        Path("OVMF_VARS.fd"),
        Path("casulo.img"),
        Path("model.gguf"),
        memory_mib=4096,
    )
    assert command[command.index("-m") + 1] == "4096M"
    try:
        runner.build_command(
            Path("qemu-system-x86_64"),
            Path("OVMF_CODE.fd"),
            Path("OVMF_VARS.fd"),
            Path("casulo.img"),
            Path("model.gguf"),
            memory_mib=1024,
        )
    except ValueError as error:
        assert "256, 4096 or 6144" in str(error)
    else:
        raise AssertionError("unfrozen memory profile accepted")


def test_paged_runner_can_boot_without_qemu_model_transport() -> None:
    runner = load_runner()
    command = runner.build_command(
        Path("qemu-system-x86_64"),
        Path("OVMF_CODE.fd"),
        Path("OVMF_VARS.fd"),
        Path("casulo-physical.img"),
        None,
        memory_mib=6144,
    )
    assert "-fw_cfg" not in command
    assert "readonly=on,file=casulo-physical.img" in " ".join(str(item) for item in command)


def test_paged_runner_preserves_claim_boundary() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert '"first_model_derived_token": False' in source
    assert '"full_sha256_computed_by_guest": False' in source
    assert '"physical_device_written": False' in source
    assert "shell=True" not in source
    ast.parse(source)


def test_paged_metrics_extract_only_native_model_receipts() -> None:
    runner = load_runner()
    metrics = runner.paged_metrics(
        "noise=1\n"
        "CASULO_NATIVE_MODEL_PAGED_CACHE_PAGES=7\n"
        "CASULO_NATIVE_MODEL_PAGED_GATE=PASS\n"
    )
    assert metrics == {
        "CASULO_NATIVE_MODEL_PAGED_CACHE_PAGES": "7",
        "CASULO_NATIVE_MODEL_PAGED_GATE": "PASS",
    }


def test_neural_port_builder_defaults_to_corrected_v3_system_pack() -> None:
    source = (ROOT / "os/tools/build_native_neural_port_image.py").read_text(encoding="utf-8")
    assert 'DEFAULT_PACK = RELEASE / "casulo-native-neural-port-system-pack-v3.cspk"' in source
    assert 'DEFAULT_PACK = RELEASE / "casulo-native-neural-port-system-pack-v1.cspk"' not in source


def test_neural_port_builder_exposes_physical_ramdisk_stage() -> None:
    source = (ROOT / "os/tools/build_native_neural_port_image.py").read_text(encoding="utf-8")
    assert '"np11"' in source
    assert "NP11_PHYSICAL_RAMDISK_MODEL_TRANSPORT" in source


def test_physical_pack_builder_uses_streaming_model_entry() -> None:
    source = (ROOT / "os/tools/build_native_physical_creation_pack.py").read_text(encoding="utf-8")
    assert "build_from_paths" in source
    assert '"NATIVE_MODEL_GGUF"' in source
    assert "MODEL_BYTES = 2_497_280_256" in source
    assert ".read_bytes()" not in source
