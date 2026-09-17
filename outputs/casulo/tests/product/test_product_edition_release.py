from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "build_product_editions",
    ROOT / "tools/build_product_editions.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_three_edition_supply_chains_are_distinct() -> None:
    assert set(MODULE.EDITIONS) == {"owner", "public", "cloud-standby"}
    projects = {edition.project for edition in MODULE.EDITIONS.values()}
    boundaries = {edition.engine_boundary for edition in MODULE.EDITIONS.values()}
    assert len(projects) == len(boundaries) == 3
    assert MODULE.EDITIONS["public"].redistributable is True
    assert MODULE.EDITIONS["owner"].redistributable is False
    assert MODULE.EDITIONS["cloud-standby"].redistributable is False


def test_release_builder_requires_explicit_keys_and_never_embeds_private_key() -> None:
    source = (ROOT / "tools/build_product_editions.py").read_text(encoding="utf-8")
    assert "explicit edition signing key" in source
    assert "ssh-keygen\", \"-Y\", \"sign" in source
    assert "read_bytes())" in source  # public key copy only
    assert "signing_key.read_bytes" not in source
