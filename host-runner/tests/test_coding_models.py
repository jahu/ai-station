import json
from types import SimpleNamespace

from ai_station_runner import coding_models as module


def test_codex_catalog_returns_only_visible_model_metadata(tmp_path, monkeypatch):
    module._cache.clear()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "models_cache.json").write_text(
        json.dumps(
            {
                "identity": "not for API",
                "models": [
                    {
                        "slug": "test-model",
                        "display_name": "Test model",
                        "visibility": "list",
                        "private": "not returned",
                    },
                    {"slug": "hidden", "visibility": "hidden"},
                ],
            }
        )
    )
    assert module.coding_models("codex")["models"] == [{"id": "test-model", "name": "Test model"}]
    module._cache.clear()


def test_cursor_catalog_uses_listing_only_and_handles_failure(monkeypatch):
    module._cache.clear()
    monkeypatch.setattr(module.shutil, "which", lambda _: "/cli/cursor-agent")

    def run(argv, **kwargs):
        assert argv == ["/cli/cursor-agent", "--list-models", "--disable-auto-update"]
        return SimpleNamespace(stdout="Available models\nauto - Auto (default)\nmodel-a - Model A\n")

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.coding_models("cursor")["models"][-1] == {"id": "model-a", "name": "Model A"}
    module._cache.clear()
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    assert module.coding_models("cursor")["notice"]
    module._cache.clear()
