import runpy
from pathlib import Path

from ai_station_runner.source_identity import source_fingerprint


def test_identity_tracks_python_names_and_bytes_but_not_checkout_or_bytecode(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    for package in (first, second):
        package.mkdir()
        (package / "worker.py").write_text("VALUE = 1\n")
    expected = source_fingerprint(first)
    assert source_fingerprint(second) == expected
    (second / "__pycache__").mkdir()
    (second / "__pycache__/worker.pyc").write_bytes(b"bytecode")
    (second / "__pycache__/ignored.py").write_text("cache")
    (second / "local.env").write_text("SECRET=must-not-affect-identity")
    assert source_fingerprint(second) == expected
    (second / "worker.py").write_text("VALUE = 2\n")
    assert source_fingerprint(second) != expected
    (second / "worker.py").write_text("VALUE = 1\n")
    (second / "worker.py").rename(second / "other.py")
    assert source_fingerprint(second) != expected


def test_loaded_identity_does_not_relabel_running_code_after_disk_changes(tmp_path):
    source = Path(__file__).parents[1] / "ai_station_runner/source_identity.py"
    copied = tmp_path / "source_identity.py"
    copied.write_bytes(source.read_bytes())
    payload = tmp_path / "worker.py"
    payload.write_text("VALUE = 1\n")
    loaded = runpy.run_path(str(copied))
    captured = loaded["SOURCE_FINGERPRINT"]
    payload.write_text("VALUE = 2\n")
    assert loaded["SOURCE_FINGERPRINT"] == captured
    assert loaded["source_fingerprint"]() != captured
