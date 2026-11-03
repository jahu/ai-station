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


def test_gui_failure_coordinates_are_available_before_its_modal_dialog(capsys):
    import desktop

    try:
        raise OSError(13, "PRIVATE_ACCOUNT_AND_SETUP_URL", "/PRIVATE_FILE")
    except OSError as error:
        desktop.startup_failure(error)
    captured = capsys.readouterr()
    assert captured.out == ""
    value = json.loads(captured.err)["desktop_startup_error"]
    assert value["error_type"] == "PermissionError"
    assert value["errno"] == 13
    assert value["frames"][-1]["file"] == "test_macos_consumer_probe.py"
    assert "PRIVATE" not in captured.err


def test_only_fixed_startup_codes_are_reported_and_restart_does_not_reuse_old_phase(tmp_path):
    log = tmp_path / "commands.log"
    old = '{"desktop_startup_stage": "application_services"}\n'
    log.write_text(old + '{"desktop_startup_stage": "PRIVATE_SETUP_URL"}\nPRIVATE_OTHER_LINE\n')
    assert probe.startup_stage(log) == "application_services"
    assert probe.startup_stage(log, after=len(old.encode())) is None
    with log.open("a") as output:
        output.write('{"desktop_startup_stage": "private_bridge", "password": "PRIVATE_FIELD"}\n')
    assert probe.startup_stage(log, after=len(old.encode())) == "private_bridge"


def test_gui_progress_emits_only_a_known_startup_code(monkeypatch, capsys):
    import desktop

    stages = []
    progress = desktop.Preparation.__new__(desktop.Preparation)
    progress.native = type("Native", (), {"stage": lambda _, value: stages.append(value)})()
    progress.proc = None
    progress.stage("PRIVATE_PRESENTATION_TEXT")
    assert capsys.readouterr().out == ""
    progress.stage("Checking private communication and your data filesystem…")
    assert json.loads(capsys.readouterr().out) == {"desktop_startup_stage": "private_bridge"}
    assert stages[0] == "PRIVATE_PRESENTATION_TEXT"


def test_service_diagnostics_inspect_only_the_owned_project_without_secret_log_fields(tmp_path, monkeypatch):
    from types import SimpleNamespace

    (tmp_path / "desktop.env").write_text('COMPOSE_PROJECT_NAME="ai-station-desktop-0123456789ab"\n')
    identity = "a" * 64
    calls = []
    engine = SimpleNamespace(command=lambda *args: ["/fixed/docker", *args], environment={"PATH": "/bin"})

    def query(argv, **kwargs):
        calls.append((argv, kwargs))
        if "ls" in argv:
            return SimpleNamespace(returncode=0, stdout=identity + " ai-station\n" + "b" * 64 + " other\n")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "Status": "running",
                    "ExitCode": 0,
                    "OOMKilled": False,
                    "Error": "PRIVATE_ERROR",
                    "Health": {"Status": "starting", "Log": [{"Output": "PRIVATE_SETUP_URL"}]},
                }
            ),
        )

    monkeypatch.setattr(probe.subprocess, "run", query)
    value = probe.service_states(engine, tmp_path)
    assert value == [
        {
            "service": "ai-station",
            "status": "running",
            "exit_code": 0,
            "oom_killed": False,
            "health": "starting",
        }
    ]
    assert len(calls) == 2
    assert "label=com.docker.compose.project=ai-station-desktop-0123456789ab" in calls[0][0]
    assert calls[1][0][1:4] == ["container", "inspect", identity]
    assert all(kwargs["timeout"] == 5 and kwargs["capture_output"] for _, kwargs in calls)
    assert "PRIVATE" not in json.dumps(value)


def test_missing_owned_project_cannot_query_any_docker_containers(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **kw: pytest.fail("Unexpected Docker query"))
    assert probe.service_states(None, tmp_path) == {"unavailable": "NoOwnedProject"}


def test_sdk_cache_snapshot_reports_only_metadata_and_hash_and_never_follows_a_link(tmp_path, monkeypatch):
    import hashlib

    from ai_station_runner.darwin_llama_environment import Environment

    raw = b"private fixture bytes must not be published"
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(
        Environment, "recipe", lambda _: {"inputs": [{"sha256": digest, "size_bytes": len(raw)}]}
    )
    target = tmp_path / "data/models/store" / digest
    assert probe.sdk_cache_state(tmp_path) == {"exists": False}
    target.parent.mkdir(parents=True)
    target.write_bytes(raw)
    target.chmod(0o444)
    value = probe.sdk_cache_state(tmp_path)
    assert value["sha256_matches"] and value["link_count"] == 1
    assert value["uid"] == value["native_uid"]
    assert value["mode"] == "0o444" and value["diagnostic_only"]
    assert raw.decode() not in json.dumps(value)
    target.unlink()
    target.symlink_to(tmp_path / "PRIVATE_EXTERNAL_FILE")
    monkeypatch.setattr(probe.hashlib, "file_digest", lambda *a: pytest.fail("Followed a cache symlink"))
    value = probe.sdk_cache_state(tmp_path)
    assert value["symlink"] and "sha256_matches" not in value
    assert "PRIVATE" not in json.dumps(value)


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
