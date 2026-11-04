"""Explicit inference fixture policy; normal tests download/execute no model."""

import json
from types import SimpleNamespace

import macos_ci_inference as probe
import pytest


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    state = {"root": tmp_path / "new-fixture", "downloads": [], "runs": [], "failure": False}
    monkeypatch.setattr(probe, "platform", SimpleNamespace(system=lambda: "Darwin", machine=lambda: "arm64"))
    monkeypatch.setattr(probe.native.bundle, "recipe", lambda *a: {"inputs": [{"filename": "fixed-sdk"}]})
    monkeypatch.setattr(
        probe.native, "collect", lambda *a: {"memory": {"source": "darwin", "available_mib": 4096}}
    )

    def fetch(root, frozen, check):
        check()
        state["downloads"].append((root, frozen))

    def run(*args, **kwargs):
        state["runs"].append((args, kwargs))
        result = {
            "status": "passed_native_probe_only",
            "native_inference_passed": True,
            "owned_stop_confirmed": True,
            "macos_installer_qualified": False,
            "socket_root": "PRIVATE-CI-PATH",
            "stdout": "PRIVATE-CONTENT",
        }
        if state["failure"]:
            output = args[1]
            output.mkdir(mode=0o700)
            (output / "proof.json").write_text(
                json.dumps(result | {"status": "failed", "error_type": "ValueError"})
            )
            raise ValueError("PRIVATE-DETAILS")
        return result

    monkeypatch.setattr(probe, "fetch", fetch)
    monkeypatch.setattr(probe, "run", run)
    return state


def test_normal_checks_cannot_implicitly_fetch_or_run_a_model(fixture):
    with pytest.raises(RuntimeError, match="opt-in"):
        probe.experiment(fixture["root"])
    assert not fixture["root"].exists() and not fixture["downloads"] and not fixture["runs"]


def test_linux_cannot_create_an_inference_fixture_even_with_the_opt_in(fixture, monkeypatch):
    monkeypatch.setattr(probe.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError):
        probe.experiment(fixture["root"], opted_in=True)
    assert not fixture["root"].exists() and not fixture["downloads"]


def test_opted_in_fixture_uses_only_fixed_public_inputs_and_scoped_cpu_probe(fixture, capsys):
    result = probe.experiment(fixture["root"], opted_in=True)
    assert result["native_inference_passed"] and result["owned_stop_confirmed"]
    assert not result["macos_installer_qualified"]
    assert fixture["root"].stat().st_mode & 0o777 == 0o700
    root, frozen = fixture["downloads"][0]
    assert root == fixture["root"] / "data" and frozen["inputs"][-1] == probe.fixture()["model"]
    args, kwargs = fixture["runs"][0]
    assert args[0] == root and args[1] == fixture["root"] / "proof" and args[-2:] == ("cpu", 512)
    assert kwargs == {"opted_in": True, "cross_process": True}
    assert "PRIVATE" not in capsys.readouterr().out and "socket_root" not in result


def test_existing_fixture_is_not_replayed_or_changed(fixture):
    fixture["root"].mkdir(mode=0o700)
    marker = fixture["root"] / "keep"
    marker.write_text("original")
    with pytest.raises(FileExistsError):
        probe.experiment(fixture["root"], opted_in=True)
    assert marker.read_text() == "original" and not fixture["downloads"]


def test_failed_probe_keeps_private_proof_but_exports_only_safe_status(fixture, capsys):
    fixture["failure"] = True
    with pytest.raises(ValueError):
        probe.experiment(fixture["root"], opted_in=True)
    assert (fixture["root"] / "proof/proof.json").exists()
    output = capsys.readouterr().out
    assert '"status": "failed"' in output and "PRIVATE" not in output


def test_changed_model_locator_is_rejected_before_any_network_or_execution(fixture, monkeypatch, tmp_path):
    value = probe.fixture()
    value["model"]["url"] = "http://127.0.0.1/private"
    location = tmp_path / "source/packaging/macos"
    location.mkdir(parents=True)
    (location / "inference-fixture.json").write_text(json.dumps(value))
    monkeypatch.setattr(probe, "ROOT", location.parents[1])
    with pytest.raises(ValueError, match="fixture changed"):
        probe.experiment(fixture["root"], opted_in=True)
    assert not fixture["downloads"] and not fixture["root"].exists()
