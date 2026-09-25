import json

from ai_station_runner.runtime_observation import observe


def process(proc, pid, name, *, start=100, args=b"", state="S"):
    folder = proc / str(pid)
    folder.mkdir()
    (folder / "comm").write_text(name)
    (folder / "cmdline").write_bytes(args)
    fields = [state] + ["0"] * 18 + [str(start)]
    (folder / "stat").write_text(f"{pid} ({name}) " + " ".join(fields))


def root(tmp_path):
    (tmp_path / "sys/kernel/random").mkdir(parents=True)
    (tmp_path / "sys/kernel/random/boot_id").write_text("test-boot")
    return tmp_path


def test_only_recognized_processes_and_no_command_secrets(tmp_path):
    proc = root(tmp_path)
    process(proc, 101, "ollama", args=b"ollama\0serve\0secret-token\0")
    process(proc, 102, "python3", args=b"python3\0/home/test/ComfyUI/main.py\0--api-key\0secret\0")
    process(proc, 103, "python3", args=b"python3\0unrelated.py\0")
    process(proc, 104, "llama-server", state="Z")
    result = observe(proc)
    assert result["complete"]
    assert {row["runtime_key"] for row in result["instances"]} == {"ollama", "comfyui"}
    assert "secret" not in json.dumps(result) and "home" not in json.dumps(result)
    old = next(row for row in result["instances"] if row["pid"] == 101)["identity"]
    folder = proc / "101/stat"
    folder.write_text(folder.read_text().removesuffix("100") + "200")
    updated = next(row for row in observe(proc)["instances"] if row["pid"] == 101)
    assert updated["identity"] != old


def test_limits_and_unreadable_metadata_mark_partial(tmp_path, monkeypatch):
    proc = root(tmp_path)
    process(proc, 101, "ollama")
    process(proc, 102, "llama-server")
    monkeypatch.setattr("ai_station_runner.runtime_observation.MAX_INSTANCES", 1)
    assert not observe(proc)["complete"]
    monkeypatch.setattr("ai_station_runner.runtime_observation.MAX_INSTANCES", 200)
    (proc / "101/stat").write_text("invalid")
    assert not observe(proc)["complete"]


def test_typed_api_exposes_read_only_observation(monkeypatch):
    from ai_station_runner.app import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        "ai_station_runner.app.observe", lambda: {"instances": [], "complete": True, "inspected": 0}
    )
    api = TestClient(app)
    assert api.get("/v1/runtimes/observe").json()["complete"]
    assert api.post("/v1/runtimes/observe", json={"command": "stop"}).status_code == 405
