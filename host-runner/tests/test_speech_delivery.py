import pytest
from ai_station_runner.audio import AudioRequest
from ai_station_runner.speech_chunks_job import delivery_arguments
from ai_station_runner.speech_delivery import inspect_delivery
from pydantic import ValidationError


def test_capability_probe_never_executes_configured_python(tmp_path):
    script = tmp_path / "clone.py"
    script.write_text(
        "raise RuntimeError('must not run')\n"
        + "\n".join(
            f"parser.add_argument({flag!r})"
            for flag in ("--ref", "--text", "--out", "--cfg", "--exaggeration", "--temperature")
        )
    )
    assert inspect_delivery(script)["version"] == "chatterbox-controls-v1"
    first = inspect_delivery(script)["source_sha256"]
    script.write_text(script.read_text() + "\n# new installation\n")
    assert inspect_delivery(script)["source_sha256"] != first
    script.write_text(script.read_text().replace("'--cfg'", "'--unknown'"))
    assert inspect_delivery(script) is None


@pytest.mark.parametrize(
    "delivery",
    [
        {"exaggeration": 0.8, "cfg_weight": 0.4, "temperature": "$(touch /tmp/escape)"},
        {"exaggeration": 0.8, "cfg_weight": True, "temperature": 0.6},
        {"exaggeration": 0.8, "cfg_weight": 0.4, "temperature": float("nan")},
        {"exaggeration": 0.8, "cfg_weight": 0.4, "temperature": 3},
        {"extra_arguments": ["--arbitrary"]},
    ],
)
def test_chunk_job_rejects_unbounded_or_command_like_options(delivery):
    with pytest.raises(ValueError):
        delivery_arguments(delivery)


def test_native_controls_require_real_values_before_dispatch():
    from uuid import uuid4

    body = {
        "run_id": uuid4(),
        "text": "Witaj",
        "reference_relative": "artifacts/ref.wav",
        "gpu": 0,
        "permissions": ["filesystem_read", "workspace_write"],
    }
    for invalid in ({"temperature": "0.6"}, {"cfg_weight": float("inf")}, {"exaggeration": False}):
        with pytest.raises(ValidationError):
            AudioRequest(**body, delivery=invalid)
    with pytest.raises(ValidationError):
        AudioRequest(**body, delivery_source_sha256="not a hash")
    assert delivery_arguments(None) == []
