from __future__ import annotations

from pathlib import Path

import pytest

from casulo.t import cli


ROOT = Path(__file__).resolve().parents[2]


def test_legacy_research_command_is_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv(cli.LEGACY_RESEARCH_ENV, raising=False)
    with pytest.raises(SystemExit) as error:
        cli.main(["benchmark", ".", "--data", "{}"])
    message = str(error.value)
    assert "bloqueado no perfil de produto" in message
    assert cli.LEGACY_RESEARCH_ENV in message


def test_explicit_opt_in_is_recognized(monkeypatch) -> None:
    monkeypatch.setenv(cli.LEGACY_RESEARCH_ENV, "1")
    cli._guard_legacy_research("benchmark")


def test_product_doctor_does_not_probe_pytorch(monkeypatch, capsys) -> None:
    def forbidden_probe(*args, **kwargs):
        raise AssertionError("PyTorch não pode ser sondado pelo doctor padrão")

    monkeypatch.setattr(cli, "probe_pytorch_runtime", forbidden_probe)
    assert cli.main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "PyTorch: não sondado" in output
    assert "Pesquisa histórica: arquivada" in output


def test_default_workflows_do_not_run_scientific_campaigns() -> None:
    for relative in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
        workflow = (ROOT / relative).read_text(encoding="utf-8")
        assert ".[science,dev]" not in workflow
        assert "simd-benchmark" not in workflow
        assert "t experiment" not in workflow
        assert "training-experiment" not in workflow
        assert "casulo-energy" not in workflow
