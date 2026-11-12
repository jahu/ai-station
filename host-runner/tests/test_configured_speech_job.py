"""Exercise the app-owned launcher without importing an SDK or using a GPU."""

import socket
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import configured_speech_job as job
from ai_station_runner import managed_speech_job


@pytest.mark.parametrize("language", ["en", "pl"])
@pytest.mark.parametrize("adapter", ["configured", "managed"])
def test_language_reaches_sdk_and_output_is_published_without_overwrite(
    tmp_path, monkeypatch, language, adapter
):
    calls = []
    seeds = []

    class Audio:
        ndim = 2
        shape = (1, 24000)

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            import numpy as np

            return np.full((1, 24000), 0.1)

    class Model:
        sr = 24000

        @classmethod
        def from_pretrained(cls, **options):
            assert options == {"device": "cuda", "t3_model": "v3"}
            return cls()

        @classmethod
        def from_local(cls, models, **options):
            assert models == tmp_path / "models"
            assert options == {"device": "cuda", "t3_model": "v3"}
            return cls()

        def generate(self, text, **options):
            assert len(seeds) == len(calls) + 1 and seeds[-1] == 42
            calls.append((text, options))
            return Audio()

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            cuda=SimpleNamespace(
                is_available=lambda: True,
                reset_peak_memory_stats=lambda: None,
                max_memory_allocated=lambda: 0,
            ),
            manual_seed=seeds.append,
            isfinite=lambda _: SimpleNamespace(all=lambda: True),
        ),
    )
    monkeypatch.setitem(sys.modules, "chatterbox", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", SimpleNamespace(ChatterboxMultilingualTTS=Model))

    def save(path, audio, rate, **_options):
        from pathlib import Path

        assert rate == 24000
        Path(path).write_bytes(b"fake test PCM")

    monkeypatch.setitem(sys.modules, "torchaudio", SimpleNamespace(save=save))
    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(write=save))
    monkeypatch.setattr(socket.socket, "connect", socket.socket.connect)
    monkeypatch.setattr(socket, "create_connection", socket.create_connection)
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        monkeypatch.setenv(key, "1")
    monkeypatch.setenv("PKUSEG_HOME", str(tmp_path))
    identity = uuid4()
    if adapter == "managed":
        import json

        from ai_station_runner import memory_scope

        (tmp_path / "ready.json").write_text(
            json.dumps({"environment_prepared": True, "profile": "chatterbox-v3-linux-x86-64-python312-v1"})
        )
        monkeypatch.setattr(memory_scope, "require_scope", lambda run_id, ram: None)
    out = tmp_path / "voice.wav"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "speech",
            "--ref",
            str(tmp_path / "ref.wav"),
            "--text",
            "Hello there. " * (40 if adapter == "managed" else 1),
            "--out",
            str(out),
            "--language",
            language,
            *(["--run-id", str(identity), "--environment", str(tmp_path)] if adapter == "managed" else []),
        ],
    )
    entry = managed_speech_job if adapter == "managed" else job
    entry.main()
    assert calls[0][1]["language_id"] == language
    assert seeds == [42] * len(calls)
    assert len(calls) >= (3 if adapter == "managed" else 1)
    assert out.read_bytes() == b"fake test PCM"
    with pytest.raises(RuntimeError, match="network"):
        socket.create_connection(("example.org", 443))
    with pytest.raises(SystemExit):
        entry.main()
    assert len(seeds) == len(calls)
