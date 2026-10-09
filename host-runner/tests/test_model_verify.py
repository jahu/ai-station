from uuid import uuid4

import pytest
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.model_verify import VerifyModel, verify_model
from fastapi import HTTPException


def test_verify_stats_file_and_never_opens_or_pulls(tmp_path, monkeypatch):
    from ai_station_runner import llama_runtime as llama

    root = tmp_path / "llm"
    root.mkdir()
    model = root / "model.gguf"
    model.write_bytes(b"GGUFbytes")
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", str(root))
    monkeypatch.setenv("AI_STATION_LLAMA_IMAGE", "ghcr.io/ggml-org/llama.cpp:server-cuda")
    clear_settings_cache()
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        assert "pull" not in args
        if args[:2] == ("image", "inspect"):
            return "sha256:" + "a" * 64
        raise AssertionError(args)

    monkeypatch.setattr(llama, "docker", docker)
    before = model.read_bytes()
    report = verify_model(
        VerifyModel(
            run_id=uuid4(),
            host_path=str(model),
            size_bytes=model.stat().st_size,
            mtime=model.stat().st_mtime,
            check_image=True,
            permissions=["filesystem_read", "manage_models"],
        )
    )
    assert report["present"] and report["matches_observation"] and report["image"]["present"]
    assert model.read_bytes() == before
    assert calls == [("image", "inspect", "ghcr.io/ggml-org/llama.cpp:server-cuda", "--format", "{{.Id}}")]
    with pytest.raises(HTTPException) as denied:
        verify_model(
            VerifyModel(
                run_id=uuid4(),
                host_path=str(model),
                size_bytes=model.stat().st_size,
                mtime=model.stat().st_mtime,
                permissions=[],
            )
        )
    assert denied.value.status_code == 403
    clear_settings_cache()
