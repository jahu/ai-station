"""An expensive fresh-host experiment cannot silently execute as a normal test."""

import json

import macos_consumer_probe as probe
import macos_native_ui_probe as ui_probe
import macos_qa_status as qa_status
import pytest


def test_ordinary_host_is_rejected_before_directories_or_subprocesses(monkeypatch):
    monkeypatch.delenv("AI_STATION_REAL_MAC_CONSUMER_TESTS", raising=False)
    monkeypatch.setattr(probe.Path, "home", lambda: pytest.fail("Accessed a real home before opt-in"))
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **kw: pytest.fail("Unexpected real process"))
    with pytest.raises(ValueError, match="explicit fresh standard public Intel"):
        probe.main()


def test_failure_evidence_locates_code_without_exception_or_local_contents():
    private_material = "PRIVATE_SETUP_LINK_AND_ACCOUNT_FIXTURE"
    try:
        raise RuntimeError(private_material)
    except RuntimeError as error:
        detail = probe.failure(error)
    assert detail["error_type"] == "RuntimeError"
    assert detail["failure_site"]["file"] == "test_macos_consumer_probe.py"
    assert detail["failure_site"]["line"] > 0
    assert private_material not in json.dumps(detail)
    assert "/home/" not in json.dumps(detail)


def test_missing_dependency_reports_only_its_module_identity():
    error = ModuleNotFoundError("PRIVATE_EXCEPTION_MESSAGE", name="ai_station_runner")
    assert probe.failure(error) == {
        "error_type": "ModuleNotFoundError",
        "missing_module": "ai_station_runner",
    }


def test_failed_owned_sdk_retains_native_fault_coordinates_without_log_contents(monkeypatch):
    identity = "9299cb43-2908-4886-82f9-2db14d828be7"
    run = {
        "id": identity,
        "status": "failed",
        "error_type": "RuntimePreparationFailed",
        "error_message": "PRIVATE_SETUP_LINK HTTP Error 403: Forbidden",
    }
    events = [
        {
            "event_type": "stderr",
            "payload": {
                "text": 'Traceback (most recent call last):\n  File "/PRIVATE_HOME/native_llama_environment_job.py", '
                'line 41, in main\n    PRIVATE_SOURCE_LINE\n  File "/PRIVATE_HOME/speech_environment.py", '
                "line 62, in verified_object\nValueError: PRIVATE_ACCOUNT_AND_EXCEPTION\n"
            },
        },
        {"event_type": "stdout", "payload": {"text": "PRIVATE_PROMPT"}},
    ]
    client = probe.Client("http://127.0.0.1:8765")
    calls = []

    def request(path):
        calls.append(path)
        return events if path.endswith("/events") else {"run": run}

    monkeypatch.setattr(client, "request", request)
    with pytest.raises(probe.RunFailed) as caught:
        client.wait("/api/setup/runtimes/preparations/owned-task")
    detail = probe.failure(caught.value)
    evidence = detail["owned_run_failure"]
    assert evidence["id"] == identity
    assert evidence["error_type"] == "RuntimePreparationFailed"
    assert evidence["native_error_type"] == "ValueError"
    assert evidence["native_frames"][-1] == {
        "file": "speech_environment.py",
        "line": 62,
        "function": "verified_object",
    }
    assert evidence["http_status"] == [403]
    assert calls[-1] == "/api/runs/" + identity + "/events"
    assert "PRIVATE" not in json.dumps(detail)


def test_run_inspection_failure_does_not_hide_original_terminal_run(monkeypatch):
    run = {"id": "9299cb43-2908-4886-82f9-2db14d828be7", "status": "failed", "error_type": "DownloadFailed"}
    client = probe.Client("http://127.0.0.1:8765")

    def request(path):
        if path.endswith("/events"):
            raise OSError("PRIVATE_RESPONSE")
        return run

    monkeypatch.setattr(client, "request", request)
    with pytest.raises(probe.RunFailed) as caught:
        client.wait("/api/runs/" + run["id"])
    assert caught.value.evidence["error_type"] == "DownloadFailed"
    assert caught.value.evidence["native_frames"] == []


def test_native_ui_fixture_refuses_normal_hosts_before_storage_or_processes(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(ui_probe.Path, "mkdir", lambda *a, **kw: pytest.fail("Unexpected fixture storage"))
    monkeypatch.setattr(ui_probe.subprocess, "run", lambda *a, **kw: pytest.fail("Unexpected compiler"))
    monkeypatch.setattr(ui_probe.subprocess, "Popen", lambda *a, **kw: pytest.fail("Unexpected UI process"))
    with pytest.raises(ValueError, match="explicit fresh public Intel"):
        ui_probe.main()


def test_installed_app_and_producer_do_not_receive_ci_publication_authority(monkeypatch):
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "GITHUB_ACTIONS"):
        monkeypatch.setenv(key, "PRIVATE_CI_FIXTURE")
    monkeypatch.setenv("RUNNER_TRACKING_ID", "owned-process-tracking")
    environment = probe.execution_environment()
    assert not any(key.startswith(("GH_", "GITHUB_", "ACTIONS_")) for key in environment)
    assert environment["RUNNER_TRACKING_ID"] == "owned-process-tracking"
    assert "PRIVATE_CI_FIXTURE" not in json.dumps(environment)


def test_public_stage_status_uses_fixed_repo_and_token_only_in_environment(monkeypatch):
    from types import SimpleNamespace

    for key, value in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "jahu/ai-station",
        "GITHUB_ACTOR": "jahu",
        "GITHUB_RUN_ID": "12345",
        "GH_TOKEN": "PRIVATE_CI_FIXTURE",
    }.items():
        monkeypatch.setenv(key, value)
    calls = []

    def invoke(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(qa_status.subprocess, "run", invoke)
    publisher = qa_status.Status("a" * 40)
    monkeypatch.delenv("GH_TOKEN")
    publisher.post("pending", "prepare_native_engine; availableRAM=1234MiB")
    argv, options = calls[0]
    assert "repos/jahu/ai-station/statuses/" + "a" * 40 in argv
    payload = json.loads(options["input"])
    assert payload["context"] == "qa/macos-consumer/12345"
    assert payload["state"] == "pending"
    assert "PRIVATE_CI_FIXTURE" not in " ".join(argv) + options["input"].decode()
    assert options["env"]["GH_TOKEN"] == "PRIVATE_CI_FIXTURE"


def test_stage_publisher_refuses_an_ordinary_environment_without_network(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(qa_status.subprocess, "run", lambda *a, **kw: pytest.fail("Unexpected GitHub API"))
    with pytest.raises(ValueError, match="explicit owner-dispatched"):
        qa_status.Status("a" * 40)


def test_existing_desktop_without_this_job_receipt_cannot_be_restarted(monkeypatch):
    monkeypatch.setattr(probe, "require_host", lambda: None)
    monkeypatch.setattr(probe.Path, "is_file", lambda _: False)
    monkeypatch.setattr(probe, "producer", lambda: pytest.fail("Accessed producer before ownership"))
    previous_umask = probe.os.umask(0o077)
    try:
        with pytest.raises(ValueError, match="fresh private Desktop installation receipt"):
            probe.main()
    finally:
        probe.os.umask(previous_umask)
