"""Bundled-interpreter inference gates; normal tests use no real model or network."""

from copy import deepcopy

import macos_ci_inference as fixture_probe
import macos_package_import_probe as probe
import pytest


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (["probe", "arm64"], False),
        (["probe", "x86_64", "--run-native-inference"], True),
    ],
)
def test_real_model_execution_requires_the_explicit_argument(arguments, expected):
    assert probe.inference_requested(arguments) is expected


@pytest.mark.parametrize(
    "arguments",
    [[], ["probe"], ["probe", "arm64", "--run"], ["probe", "arm64", "--run-native-inference", "extra"]],
)
def test_ambiguous_arguments_cannot_opt_in(arguments):
    with pytest.raises(RuntimeError, match="explicit inference"):
        probe.inference_requested(arguments)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    result = {"architecture": "arm64", "model_inference_tested": False, "macos_installer_qualified": False}
    proof = {
        "status": "passed_native_probe_only",
        "architecture": "arm64",
        "compute": "cpu",
        "context_size": 512,
        "model_sha256": fixture_probe.fixture()["model"]["sha256"],
        "native_inference_passed": True,
        "cross_process_restart_tested": True,
        "owner_process_exit_confirmed": True,
        "owned_stop_confirmed": True,
        "socket_cleanup_confirmed": True,
        "stdout": "PRIVATE",
        "socket_root": "/PRIVATE/socket",
    }
    calls = []

    def experiment(root, *, opted_in):
        calls.append((root, opted_in))
        return deepcopy(proof)

    monkeypatch.setattr(fixture_probe, "experiment", experiment)
    return result, proof, calls, tmp_path / "python"


def test_fixed_cpu_probe_uses_packaged_sibling_storage_and_safe_projection(fixture):
    result, proof, calls, layer = fixture
    probe.qualify_inference(layer, result)
    assert calls == [(layer.parent / "inference", True)]
    assert result["model_inference_tested"] is True and not result["macos_installer_qualified"]
    assert result["bundled_native_inference"]["owner_process_exit_confirmed"]
    assert "PRIVATE" not in str(result)


@pytest.mark.parametrize(
    "key,value",
    [
        ("status", "failed"),
        ("architecture", "x86_64"),
        ("compute", "metal"),
        ("context_size", 4096),
        ("model_sha256", "a" * 64),
        ("native_inference_passed", False),
        ("cross_process_restart_tested", False),
        ("owner_process_exit_confirmed", False),
        ("owned_stop_confirmed", False),
        ("socket_cleanup_confirmed", False),
        ("native_inference_passed", 1),
    ],
)
def test_partial_or_different_fixture_does_not_qualify_bundled_inference(fixture, key, value):
    result, proof, calls, layer = fixture
    proof[key] = value
    with pytest.raises(ValueError, match="not fully confirmed"):
        probe.qualify_inference(layer, result)
    assert not result["model_inference_tested"] and "bundled_native_inference" not in result


def test_fixture_failure_propagates_without_success_or_consuming_existing_evidence(fixture, monkeypatch):
    result, proof, calls, layer = fixture

    def fail(*args, **kwargs):
        raise FileExistsError("retained earlier experiment")

    monkeypatch.setattr(fixture_probe, "experiment", fail)
    with pytest.raises(FileExistsError):
        probe.qualify_inference(layer, result)
    assert not result["model_inference_tested"] and "bundled_native_inference" not in result
