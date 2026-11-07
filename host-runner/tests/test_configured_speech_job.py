"""Exercise the app-owned launcher without importing an SDK or using a GPU."""

import socket
import sys
from types import SimpleNamespace

import pytest
from ai_station_runner import configured_speech_job as job


@pytest.mark.parametrize("language", ["en", "pl"])
def test_language_reaches_sdk_and_output_is_published_without_overwrite(tmp_path, monkeypatch, language):
    calls = []

    class Audio:
        ndim = 2
        shape = (1, 24000)

        def detach(self):
            return self

        def cpu(self):
            return self

    class Model:
        sr = 24000

        @classmethod
        def from_pretrained(cls, **options):
            assert options == {"device": "cuda", "t3_model": "v3"}
            return cls()

        def generate(self, text, **options):
            calls.append((text, options))
            return Audio()

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: True),
            isfinite=lambda _: SimpleNamespace(all=lambda: True),
        ),
    )
    monkeypatch.setitem(sys.modules, "chatterbox", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", SimpleNamespace(ChatterboxMultilingualTTS=Model))

    def save(path, audio, rate):
        from pathlib import Path

        assert rate == 24000
        Path(path).write_bytes(b"fake test PCM")

    monkeypatch.setitem(sys.modules, "torchaudio", SimpleNamespace(save=save))
    monkeypatch.setattr(socket.socket, "connect", socket.socket.connect)
    monkeypatch.setattr(socket, "create_connection", socket.create_connection)
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        monkeypatch.setenv(key, "1")
    out = tmp_path / "voice.wav"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "speech",
            "--ref",
            str(tmp_path / "ref.wav"),
            "--text",
            "Hello there",
            "--out",
            str(out),
            "--language",
            language,
        ],
    )
    job.main()
    assert calls[0][1]["language_id"] == language
    assert out.read_bytes() == b"fake test PCM"
    with pytest.raises(RuntimeError, match="network"):
        socket.create_connection(("example.org", 443))
    with pytest.raises(SystemExit):
        job.main()
    assert len(calls) == 1
