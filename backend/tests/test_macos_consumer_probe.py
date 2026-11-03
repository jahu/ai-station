"""An expensive fresh-host experiment cannot silently execute as a normal test."""

import hashlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import macos_consumer_probe as probe
import macos_native_ui_probe as ui_probe
import macos_qa_status as qa_status
import pytest


@pytest.mark.parametrize("selected", [None, "0", "1"])
def test_complete_probe_profiles_only_after_explicit_workflow_selection(monkeypatch, selected):
    monkeypatch.setenv("AI_STATION_RUNNER_STARTUP_PROFILE", "1")
    if selected is None:
        monkeypatch.delenv("AI_STATION_REAL_MAC_STARTUP_PROFILE", raising=False)
    else:
        monkeypatch.setenv("AI_STATION_REAL_MAC_STARTUP_PROFILE", selected)
    assert probe.select_startup_profile() == (selected == "1")
    assert os.environ.get("AI_STATION_RUNNER_STARTUP_PROFILE") == ("1" if selected == "1" else None)


@pytest.mark.parametrize("selected", ["true", "1 --arbitrary", "PRIVATE_VALUE"])
def test_complete_probe_rejects_non_boolean_profiling_settings(monkeypatch, selected):
    monkeypatch.setenv("AI_STATION_REAL_MAC_STARTUP_PROFILE", selected)
    with pytest.raises(ValueError, match="explicit boolean"):
        probe.select_startup_profile()


def test_ordinary_host_is_rejected_before_directories_or_subprocesses(monkeypatch):
    monkeypatch.delenv("AI_STATION_REAL_MAC_CONSUMER_TESTS", raising=False)
    monkeypatch.setattr(probe.Path, "home", lambda: pytest.fail("Accessed a real home before opt-in"))
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **kw: pytest.fail("Unexpected real process"))
    with pytest.raises(ValueError, match="explicit fresh standard public Intel"):
        probe.main()


def test_http_failure_reports_status_without_response_url_or_private_values():
    from urllib.error import HTTPError

    error = HTTPError("http://PRIVATE_URL", 401, "PRIVATE_MESSAGE", {}, None)
    detail = probe.failure(error)
    assert detail["http_status"] == 401 and "PRIVATE" not in json.dumps(detail)


def test_native_maintenance_waits_for_a_new_owner_instead_of_accepting_stale_readiness(monkeypatch):
    import desktop

    previous = {"url": "http://127.0.0.1:8765/?private=old", "instance_id": "a" * 32}
    current = {"url": "http://127.0.0.1:8765/?private=new", "instance_id": "b" * 32}
    observations = iter([previous, None, current])
    monkeypatch.setattr(desktop, "ready_info", lambda _: next(observations))
    waits = []
    monkeypatch.setattr(probe.time, "sleep", waits.append)
    assert probe.maintenance_ready(SimpleNamespace(poll=lambda: None), None, previous) == current
    assert waits == [1, 1]


@pytest.mark.parametrize(
    "current",
    [
        {"url": "http://127.0.0.1:8766/", "instance_id": "b" * 32},
        {"url": "https://127.0.0.1:8765/", "instance_id": "b" * 32},
        {"url": "http://127.0.0.1:8765/"},
    ],
)
def test_native_maintenance_rejects_a_changed_origin_or_missing_owner(monkeypatch, current):
    import desktop

    previous = {"url": "http://127.0.0.1:8765/", "instance_id": "a" * 32}
    monkeypatch.setattr(desktop, "ready_info", lambda _: current)
    with pytest.raises(ValueError, match="private origin or owner"):
        probe.maintenance_ready(SimpleNamespace(poll=lambda: None), None, previous)


def test_native_maintenance_child_exit_is_failure_even_if_old_readiness_remains(monkeypatch):
    import desktop

    monkeypatch.setattr(desktop, "ready_info", lambda _: pytest.fail("Accepted a stale owner"))
    with pytest.raises(RuntimeError, match="exited before"):
        probe.maintenance_ready(SimpleNamespace(poll=lambda: 0), None, {})


def test_native_maintenance_never_waits_forever_on_the_predecessor(monkeypatch):
    import desktop

    previous = {"url": "http://127.0.0.1:8765/", "instance_id": "a" * 32}
    clock = iter([0, 0, 2])
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(probe.time, "sleep", lambda _: None)
    monkeypatch.setattr(desktop, "ready_info", lambda _: previous)
    with pytest.raises(TimeoutError, match="new desktop owner"):
        probe.maintenance_ready(SimpleNamespace(poll=lambda: None), None, previous, timeout=1)


@pytest.fixture
def removable_qa_bundle(tmp_path, monkeypatch):
    import desktop

    monkeypatch.setattr(probe, "require_host", lambda: None)
    parent = tmp_path / ".tools"
    parent.mkdir(mode=0o700)
    root = parent / "mac-consumer-experiment"
    root.mkdir(mode=0o700)
    resources = root / "AI Station.app/Contents/Resources"
    resources.mkdir(parents=True)
    content = b"synthetic verified app payload"
    (resources / "payload").write_bytes(content)
    (resources / "alias").symlink_to("payload")
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(desktop, "manifest", lambda _: {"files": {"payload": digest, "alias": digest}})
    state = tmp_path / "saved-data"
    state.mkdir(mode=0o700)
    (state / "private.txt").write_bytes(b"saved accounts and models are separate")
    return root, state, content


def test_QA_app_removal_retains_verified_reinstall_source_and_private_data(removable_qa_bundle):
    root, state, content = removable_qa_bundle
    original = (state / "private.txt").read_bytes()
    retained = probe.remove_qa_application(root, state)
    assert not (root / "AI Station.app").exists()
    assert retained == root / "reinstall-source/AI Station.app"
    assert (retained / "Contents/Resources/payload").read_bytes() == content
    assert (retained / "Contents/Resources/alias").is_symlink()
    assert (state / "private.txt").read_bytes() == original


def test_QA_removal_refuses_an_existing_reinstall_copy_before_deleting_app(removable_qa_bundle):
    root, state, _ = removable_qa_bundle
    (root / "reinstall-source").mkdir()
    with pytest.raises(FileExistsError):
        probe.remove_qa_application(root, state)
    assert (root / "AI Station.app/Contents/Resources/payload").exists()


def test_QA_removal_never_deletes_app_when_reinstall_copy_fails_verification(
    removable_qa_bundle, monkeypatch
):
    root, state, content = removable_qa_bundle
    copy = probe.shutil.copytree

    def damaged(*args, **kwargs):
        result = copy(*args, **kwargs)
        if Path(args[0]).name == "AI Station.app":
            (Path(result) / "Contents/Resources/payload").write_bytes(b"incomplete copy")
        return result

    monkeypatch.setattr(probe.shutil, "copytree", damaged)
    with pytest.raises(ValueError, match="missing or changed"):
        probe.remove_qa_application(root, state)
    assert (root / "AI Station.app/Contents/Resources/payload").read_bytes() == content


def test_QA_removal_rejects_redirected_app_without_touching_its_target(removable_qa_bundle, tmp_path):
    root, state, content = removable_qa_bundle
    external = tmp_path / "unrelated.app"
    (root / "AI Station.app").rename(external)
    (root / "AI Station.app").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="restricted to this fresh QA bundle"):
        probe.remove_qa_application(root, state)
    assert (external / "Contents/Resources/payload").read_bytes() == content
    assert not (root / "reinstall-source").exists()


def test_QA_removal_refuses_saved_data_inside_the_selected_app(removable_qa_bundle):
    root, _, content = removable_qa_bundle
    with pytest.raises(ValueError, match="outside saved data"):
        probe.remove_qa_application(root, root / "AI Station.app/Contents/Resources")
    assert (root / "AI Station.app/Contents/Resources/payload").read_bytes() == content


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


@pytest.mark.parametrize("returncode,outcome", [(None, "timed_out"), (2, "exited"), (-15, "exited")])
def test_runner_readiness_distinguishes_exit_from_timeout_without_exposing_messages(
    tmp_path, capsys, returncode, outcome
):
    import desktop
    import launch

    error = launch.RunnerReadinessError(returncode)
    desktop.startup_failure(error)
    emitted = capsys.readouterr().err
    assert "Host Runner did not become healthy" not in emitted
    (tmp_path / "desktop.log").write_text('{"desktop_service_stage": "starting_runner"}\n' + emitted)
    detail = probe.startup_errors(tmp_path)
    item = detail["errors"][0]
    assert detail["stage"] == "starting_runner" and item["runner_readiness"] == outcome
    if returncode is None:
        assert "return_code" not in item
    else:
        assert item["return_code"] == returncode


@pytest.mark.parametrize("value", ["PRIVATE_VALUE", [], {"private": "value"}])
def test_readiness_diagnostics_drop_unknown_or_malformed_outcomes(tmp_path, value):
    (tmp_path / "desktop.log").write_text(
        json.dumps(
            {
                "desktop_startup_error": {
                    "error_type": "RunnerReadinessError",
                    "runner_readiness": value,
                    "frames": [],
                }
            }
        )
    )
    assert probe.startup_errors(tmp_path)["errors"] == [{"error_type": "RunnerReadinessError", "frames": []}]


def test_missing_dependency_reports_only_its_module_identity():
    error = ModuleNotFoundError("PRIVATE_EXCEPTION_MESSAGE", name="ai_station_runner")
    assert probe.failure(error) == {
        "error_type": "ModuleNotFoundError",
        "missing_module": "ai_station_runner",
    }


def test_startup_profile_keeps_only_code_timings_and_sanitized_child_faults():
    text = """import time: 13 | 472 | ai_station_runner.app
import time: 19 | 900 | PRIVATE_MODULE.SECRET
Traceback (most recent call last):
  File "/Users/PRIVATE_OWNER/PRIVATE_FOLDER/main.py", line 42, in <module>
    PRIVATE_VARIABLE = "PRIVATE_TOKEN"
pydantic_core._pydantic_core.ValidationError: PRIVATE_INPUT https://secret.invalid/?token=PRIVATE_TOKEN
The configured socket already has a listener
"""
    result = probe.startup_profile(text)
    assert result == {
        "slowest_imports": [{"module": "ai_station_runner.app", "self_us": 13, "cumulative_us": 472}],
        "unstructured_child_errors": {
            "types": ["ValidationError"],
            "frames": [{"file": "main.py", "line": 42, "function": "<module>"}],
        },
        "runner_message_codes": ["socket_owner_busy"],
    }
    assert "PRIVATE" not in json.dumps(result) and "secret.invalid" not in json.dumps(result)


def test_startup_profile_drops_malformed_or_unbounded_rows():
    assert (
        probe.startup_profile(
            "import time: " + ("9" * 5000) + " | 12 | ai_station_runner.app\nPRIVATE_ERROR: PRIVATE_TOKEN"
        )
        == {}
    )


@pytest.mark.parametrize(
    "system,desktop,isolation", [("darwin", True, ["-IB"]), ("linux", True, ["-I"]), ("linux", False, [])]
)
def test_runner_profile_is_an_explicit_fixed_diagnostic_without_arbitrary_arguments(
    monkeypatch, system, desktop, isolation
):
    import launch

    monkeypatch.setattr(launch.sys, "platform", system)
    ordinary = [sys.executable, *isolation, "-m", "ai_station_runner.main"]
    assert launch.runner_command(desktop=desktop, environment={}) == ordinary
    assert (
        launch.runner_command(
            desktop=desktop, environment={"AI_STATION_RUNNER_STARTUP_PROFILE": "1 --arbitrary PRIVATE_VALUE"}
        )
        == ordinary
    )
    assert launch.runner_command(desktop=desktop, environment={"AI_STATION_RUNNER_STARTUP_PROFILE": "1"}) == [
        sys.executable,
        *isolation,
        "-X",
        "importtime",
        "-m",
        "ai_station_runner.main",
    ]


def test_desktop_preserves_only_the_explicit_runner_diagnostic_setting(monkeypatch):
    import desktop

    monkeypatch.setenv("AI_STATION_RUNNER_STARTUP_PROFILE", "1")
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", "PRIVATE_OTHER_STATION")
    monkeypatch.setenv("PYTHONPATH", "PRIVATE_OTHER_MODULES")
    result = desktop.launch_environment()
    assert result["AI_STATION_RUNNER_STARTUP_PROFILE"] == "1"
    assert "AI_STATION_DATA_HOST_PATH" not in result and "PYTHONPATH" not in result


def test_browser_record_observation_uses_only_reads_and_waits_for_actual_publication(monkeypatch):
    client = probe.Client("http://127.0.0.1:8765")
    row = {"id": "91f0cece-c533-4081-a63f-979a1025762b", "run": {"status": "queued"}}
    results = iter([[], [row]])
    paths = []

    def request(path, body=None):
        assert body is None, "A browser acceptance assertion must not replace the UI action"
        paths.append(path)
        return next(results)

    monkeypatch.setattr(client, "request", request)
    monkeypatch.setattr(probe.time, "sleep", lambda _: None)
    assert client.created_in_browser("/api/setup/downloads") == row
    assert paths == ["/api/setup/downloads"] * 2


@pytest.mark.parametrize("rows", [{"id": "not-a-list"}, [{"id": "bad-identity"}], [{"id": "a"}, {"id": "b"}]])
def test_browser_record_observation_cannot_adopt_ambiguous_or_invalid_rows(monkeypatch, rows):
    client = probe.Client("http://127.0.0.1:8765")
    monkeypatch.setattr(client, "request", lambda _: rows)
    with pytest.raises(ValueError):
        client.created_in_browser("/api/setup/downloads")


def stopped_messages():
    return [
        {"id": "old", "role": "assistant", "content": "Earlier answer"},
        {"id": "user", "role": "user", "content": probe.STOP_PROMPT},
        {
            "id": "reply",
            "role": "assistant",
            "content": "Once upon a time…",
            "run_id": "91f0cece-c533-4081-a63f-979a1025762b",
            "metadata": {"partial": True},
        },
    ]


def test_browser_stop_observer_only_reads_and_reports_no_generated_or_account_text(monkeypatch):
    client = probe.Client("http://127.0.0.1:8765")
    messages = stopped_messages()
    paths = []

    def request(path, body=None):
        assert body is None, "Never substitute API writes for visible Stop"
        paths.append(path)
        return (
            {"status": "canceled"}
            if path.startswith("/api/runs/")
            else {"messages": messages, "active_run": None}
        )

    monkeypatch.setattr(client, "request", request)
    result = client.stopped_in_browser("4da328a1-06bf-4d26-9fab-7b590defc86f", {"old"})
    assert result["status"] == "canceled" and result["partial_preserved"]
    assert result["streamed_characters"] == len(messages[-1]["content"])
    assert paths == [
        "/api/chat/conversations/4da328a1-06bf-4d26-9fab-7b590defc86f",
        "/api/runs/" + messages[-1]["run_id"],
    ]
    assert messages[-1]["content"] not in json.dumps(result) and probe.STOP_PROMPT not in json.dumps(result)


@pytest.mark.parametrize(
    "fault", ["finished", "failed", "empty", "not_partial", "wrong_prompt", "extra_message"]
)
def test_browser_stop_cannot_pass_a_finished_empty_or_different_answer(monkeypatch, fault):
    messages = stopped_messages()
    status = "canceled"
    if fault in {"finished", "failed"}:
        status = "succeeded" if fault == "finished" else "failed"
    elif fault == "empty":
        messages[-1]["content"] = " "
    elif fault == "not_partial":
        messages[-1]["metadata"]["partial"] = False
    elif fault == "wrong_prompt":
        messages[-2]["content"] = "A different request"
    else:
        messages.append({"id": "unexpected"})
    client = probe.Client("http://127.0.0.1:8765")
    monkeypatch.setattr(
        client,
        "request",
        lambda path: (
            {"status": status}
            if path.startswith("/api/runs/")
            else {"messages": messages, "active_run": None}
        ),
    )
    with pytest.raises(ValueError):
        client.stopped_in_browser("4da328a1-06bf-4d26-9fab-7b590defc86f", {"old"})


@pytest.mark.parametrize(
    "error",
    [RuntimeError("PRIVATE_SETUP_LINK"), subprocess.CalledProcessError(17, ["PRIVATE_COMMAND"])],
)
def test_actual_desktop_supervisor_entry_reports_coordinates_without_private_arguments(
    monkeypatch, capsys, error
):
    import argparse

    source = Path(probe.__file__).with_name("launch.py")
    monkeypatch.setattr(sys, "argv", [str(source), "--desktop"])

    def refuse(_parser):
        raise error

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", refuse)
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(source), run_name="__main__")
    assert caught.value.code == str(error)  # Existing CLI error behavior is preserved.
    output = capsys.readouterr()
    assert not output.out
    value = json.loads(output.err)["desktop_startup_error"]
    assert value["error_type"] == type(error).__name__
    assert any(frame["file"] == "launch.py" and frame["function"] == "main" for frame in value["frames"])
    assert "PRIVATE" not in output.err
    if isinstance(error, subprocess.CalledProcessError):
        assert value["return_code"] == 17


def test_owned_supervisor_log_exports_only_bounded_structured_coordinates(tmp_path):
    assert probe.startup_errors(tmp_path) == {"stage": None, "errors": []}
    frame = {"file": "launch.py", "line": 315, "function": "main", "locals": "PRIVATE_ACCOUNT"}
    value = {
        "error_type": "CalledProcessError",
        "frames": [frame],
        "return_code": 17,
        "command": "PRIVATE_COMMAND",
        "message": "PRIVATE_SETUP_LINK",
    }
    path = tmp_path / "desktop.log"
    path.write_text(
        "PRIVATE_OLD_LOG" * 200000
        + '\n{"desktop_service_stage": "starting_services"}\n'
        + json.dumps({"desktop_startup_error": value})
        + "\nPRIVATE_FINAL_LINE\n"
    )
    assert probe.startup_errors(tmp_path)["errors"] == [
        {
            "error_type": "CalledProcessError",
            "frames": [{"file": "launch.py", "line": 315, "function": "main"}],
            "return_code": 17,
        }
    ]

    assert probe.startup_errors(tmp_path)["stage"] == "starting_services"


def test_owned_supervisor_log_ignores_unknown_records_and_invalid_coordinates(tmp_path):
    values = [
        {"error_type": "PRIVATE_CLASS", "frames": []},
        {
            "error_type": "RuntimeError",
            "frames": [None, {"file": "/PRIVATE/path.py", "line": 2, "function": "main"}],
            "errno": True,
            "return_code": "PRIVATE_VALUE",
        },
        [],
    ]
    (tmp_path / "desktop.log").write_text(
        '{"desktop_startup_error": invalid}\n{"desktop_service_stage": "PRIVATE_STAGE"}\n'
        + "\n".join(json.dumps({"desktop_startup_error": value}) for value in values)
    )
    assert probe.startup_errors(tmp_path)["errors"] == [{"error_type": "RuntimeError", "frames": []}]


def test_native_parent_fault_is_visible_before_waiting_for_browser_timeout(tmp_path):
    (tmp_path / "commands.private.log").write_text(
        json.dumps(
            {
                "desktop_startup_error": {
                    "error_type": "RuntimeError",
                    "frames": [{"file": "desktop.py", "line": 558, "function": "supervise"}],
                    "message": "PRIVATE_SETUP_URL",
                }
            }
        )
        + "\n"
    )
    result = probe.startup_errors(tmp_path, log_name="commands.private.log")
    assert result["errors"][0]["frames"][0]["function"] == "supervise"
    assert "PRIVATE" not in json.dumps(result)
    with pytest.raises(ValueError):
        probe.startup_errors(tmp_path, log_name="../PRIVATE_OTHER_LOG")


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_owned_supervisor_log_cannot_read_an_external_alias_or_block_on_fifo(tmp_path, kind):
    path = tmp_path / "desktop.log"
    if kind == "fifo":
        os.mkfifo(path)
    else:
        other = tmp_path / "PRIVATE_OTHER_FILE"
        other.write_text("PRIVATE_CONTENT")
        if kind == "symlink":
            path.symlink_to(other)
        else:
            os.link(other, path)
    with pytest.raises((OSError, ValueError)):
        probe.startup_errors(tmp_path)


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
    progress.cancelable = False
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


def test_live_service_faults_keep_only_known_error_classes_and_basename_frames(tmp_path, monkeypatch):
    from types import SimpleNamespace

    (tmp_path / "desktop.env").write_text('COMPOSE_PROJECT_NAME="ai-station-desktop-0123456789ab"\n')
    identity = "a" * 64
    engine = SimpleNamespace(command=lambda *args: ["/fixed/docker", *args], environment={"PATH": "/bin"})
    calls = []

    def query(argv, **kwargs):
        calls.append(argv)
        if "ls" in argv:
            return SimpleNamespace(returncode=0, stdout=identity + " ai-station\n")
        if "inspect" in argv:
            return SimpleNamespace(
                returncode=0, stdout='{"Status":"running","Health":{"Status":"unhealthy"}}'
            )
        assert argv[1:] == ["container", "logs", "--tail", "40", identity]
        return SimpleNamespace(
            returncode=0,
            stdout="PRIVATE_SETUP_URL\n",
            stderr='  File "/PRIVATE_PATH/db.py", line 12, in migrate\nsqlalchemy.exc.OperationalError: PRIVATE_PASSWORD\n',
        )

    monkeypatch.setattr(probe.subprocess, "run", query)
    item = probe.service_states(engine, tmp_path, errors=True)[0]
    assert item["startup_diagnostics"]["unstructured_child_errors"] == {
        "types": ["OperationalError"],
        "frames": [{"file": "db.py", "line": 12, "function": "migrate"}],
    }
    assert len(calls) == 3 and "PRIVATE" not in json.dumps(item)


def test_native_process_observation_keeps_owned_descendants_without_private_commands(monkeypatch):
    from types import SimpleNamespace

    output = "\n".join(
        [
            "100 1 S 0.2 00:20 /PRIVATE_HOME/AI Station",
            "101 100 S 1.5 00:19 /PRIVATE_HOME/python3.12",
            "102 101 S 0.0 00:15 /PRIVATE_HOME/docker-credential-desktop",
            "103 101 S 0.0 00:12 /PRIVATE_HOME/PRIVATE_EXECUTABLE",
            "200 1 R 5.0 00:10 /PRIVATE_HOME/docker",
            "300 301 S 0.0 00:11 /PRIVATE_HOME/python3",
            "301 300 S 0.0 00:11 /PRIVATE_HOME/python3",
        ]
    )

    def query(argv, **kwargs):
        assert argv == ["/bin/ps", "-A", "-o", "pid=,ppid=,stat=,pcpu=,etime=,comm="]
        assert kwargs["timeout"] == 5 and kwargs["capture_output"]
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(probe.subprocess, "run", query)
    value = probe.native_process_states([100])
    assert [row["pid"] for row in value] == [100, 101, 102, 103]
    assert [row["kind"] for row in value] == ["AI Station", "python", "docker-credential-desktop", "other"]
    assert "PRIVATE" not in json.dumps(value)
    with pytest.raises(ValueError):
        probe.native_process_states([True])


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


@pytest.fixture
def stage_publisher(monkeypatch):
    for key, value in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "jahu/ai-station",
        "GITHUB_ACTOR": "jahu",
        "GITHUB_RUN_ID": "12345",
        "GH_TOKEN": "PRIVATE_CI_FIXTURE",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(qa_status.time, "sleep", lambda _: None)
    return qa_status.Status("a" * 40)


def test_stage_publication_recovers_after_a_failed_attempt_without_repeating_the_workload(
    monkeypatch, stage_publisher
):
    from unittest.mock import Mock

    invoke = Mock(side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)])
    monkeypatch.setattr(qa_status.subprocess, "run", invoke)
    assert stage_publisher.post("pending", "build_real_control_plane") is True
    assert invoke.call_count == 2
    assert invoke.call_args_list[0] == invoke.call_args_list[1]


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing_cli"])
def test_exhausted_stage_publication_is_bounded_nonsecret_and_does_not_abort_actual_qa(
    monkeypatch, capsys, stage_publisher, failure
):
    from unittest.mock import Mock

    if failure == "exit":
        invoke = Mock(return_value=SimpleNamespace(returncode=1))
    else:
        error = (
            subprocess.TimeoutExpired("PRIVATE_CI_FIXTURE", 5, stderr="PRIVATE_SERVER_REPLY")
            if failure == "timeout"
            else OSError("PRIVATE_CI_FIXTURE")
        )
        invoke = Mock(side_effect=error)
    monkeypatch.setattr(qa_status.subprocess, "run", invoke)
    assert stage_publisher.post("pending", "build_real_control_plane") is False
    assert invoke.call_count == 3
    assert all(call.kwargs["timeout"] == 5 for call in invoke.call_args_list)
    emitted = capsys.readouterr().out
    assert "job log remain authoritative" in emitted and "PRIVATE" not in emitted


def test_unknown_stage_state_still_fails_before_publication(monkeypatch, stage_publisher):
    monkeypatch.setattr(qa_status.subprocess, "run", lambda *a, **kw: pytest.fail("Unexpected GitHub API"))
    with pytest.raises(ValueError, match="Unknown stage status"):
        stage_publisher.post("PRIVATE_VALUE", "not a permitted state")


def test_prerequisite_breadcrumbs_publish_only_fixed_phases_on_the_workflow_head(monkeypatch):
    from unittest.mock import Mock

    publisher = Mock()
    construct = Mock(return_value=publisher)
    monkeypatch.setattr(qa_status, "Status", construct)
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    for stage in sorted(qa_status.PREREQUISITE_STAGES):
        qa_status.publish_prerequisite(stage)
        construct.assert_called_with("a" * 40)
        publisher.post.assert_called_with("pending", "Prerequisite: " + stage)
    count = construct.call_count
    with pytest.raises(ValueError, match="Unknown fixed"):
        qa_status.publish_prerequisite("PRIVATE_PATH_OR_CREDENTIAL")
    assert construct.call_count == count


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
