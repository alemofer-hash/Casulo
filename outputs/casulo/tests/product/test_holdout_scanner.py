from pathlib import Path

from casulo_owner import generative_agent_probe


def test_holdout_scanner_uses_bounded_python_fallback_without_rg(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "source.py").write_text("needle = 'present'\n", encoding="utf-8")
    generated = tmp_path / "outputs"
    generated.mkdir()
    (generated / "ignored.py").write_text("secret holdout\n", encoding="utf-8")
    monkeypatch.setattr(generative_agent_probe.shutil, "which", lambda _name: None)
    result = generative_agent_probe._preexisting_holdout_matches(
        tmp_path, "needle", "secret holdout"
    )
    assert result["scanner"] == "bounded-python-literal-scan"
    assert len(result["findings"][0]["matches"]) == 1
    assert result["findings"][1]["matches"] == []


def test_holdout_scanner_capability_always_has_local_fallback(monkeypatch) -> None:
    monkeypatch.setattr(generative_agent_probe.shutil, "which", lambda _name: None)
    capability = generative_agent_probe.holdout_scanner_capability()
    assert capability["rg_available"] is False
    assert capability["fallback_available"] is True


def test_invalid_rg_executable_falls_back_without_traceback(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "source.md").write_text("agulha\n", encoding="utf-8")
    monkeypatch.setattr(
        generative_agent_probe.shutil,
        "which",
        lambda _name: str(tmp_path / "rg-invalido.exe"),
    )
    result = generative_agent_probe._preexisting_holdout_matches(
        tmp_path, "agulha", "ausente"
    )
    assert result["scanner"] == "bounded-python-literal-scan"
    assert len(result["findings"][0]["matches"]) == 1
    assert result["shell_used"] is False


def test_rg_nonstandard_failure_uses_same_bounded_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "source.json").write_text('{"key":"needle"}', encoding="utf-8")
    monkeypatch.setattr(generative_agent_probe.shutil, "which", lambda _name: "rg.exe")

    calls = 0

    class Result:
        stdout = ""
        stderr = ""

        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def execute(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return Result(0 if calls == 1 else 2)

    monkeypatch.setattr(generative_agent_probe.subprocess, "run", execute)
    result = generative_agent_probe._preexisting_holdout_matches(tmp_path, "needle", "missing")
    assert result["scanner"] == "bounded-python-literal-scan"
    assert result["fallback_reason"] == "rg_exit:2"
