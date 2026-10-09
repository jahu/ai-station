from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_compose_application_data_is_a_bind_mount():
    text = (ROOT / "compose.yaml").read_text()
    assert not any(line.startswith("volumes:") for line in text.splitlines())
    assert "type: bind" in text
    assert "create_host_path: false" in text
    assert "${AI_STATION_DATA_HOST_PATH:-./data}" in text
    assert "target: /data" in text


def test_launcher_compose_down_never_wipes_volumes():
    import importlib.util

    spec = importlib.util.spec_from_file_location("launch", ROOT / "scripts/launch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.COMPOSE_DOWN == ("down", "--timeout", "10")
    command = module.data_preserving_compose_down(["docker", "compose", "-f", "compose.yaml"])
    assert command[-3:] == ["down", "--timeout", "10"]
    assert "-v" not in command and "--volumes" not in command
    with pytest.raises(RuntimeError, match="must not pass"):
        module.data_preserving_compose_down(["docker", "compose", "down", "--volumes"])
    source = (ROOT / "scripts/launch.py").read_text()
    assert "data_preserving_compose_down(compose)" in source
    assert 'run("down", "--volumes"' not in source
    assert 'run("down", "-v"' not in source
