import pytest
from app.image_schema import ImageRequest
from app.images import create_image_run, fresh_seed
from app.models import Artifact


@pytest.mark.parametrize("legacy_managed_receipt", [False, True])
def test_new_qwen_runs_freeze_seed_and_avoid_legacy_or_source_noise(
    session, monkeypatch, tmp_path, legacy_managed_receipt
):
    from app.config import get_settings

    monkeypatch.setattr("app.images.secrets.randbits", lambda _: 42)
    original = create_image_run(
        session, ImageRequest(mode="t2i", backend="qwen", prompt="A cabinet", seed=43)
    )
    if legacy_managed_receipt:
        original.parameters = {
            **original.parameters,
            "seed": None,
            "managed_image_runtime": {"command": {"seed": 43}},
        }
    relative = "artifacts/source.png"
    path = get_settings().data_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"source")
    source = Artifact(run_id=original.id, artifact_type="image", relative_path=relative, metadata_json={})
    session.add(source)
    session.flush()
    for mode in ("img2img", "recompose"):
        body = ImageRequest(
            mode=mode,
            backend="qwen",
            prompt="Another view",
            edit_prompt="Another view",
            input_artifact_ids=[source.id],
        )
        run = create_image_run(session, body)
        assert run.parameters["seed"] == 44
        session.flush()
        session.expire(run)
        assert run.parameters["seed"] == 44
    assert (
        create_image_run(session, ImageRequest(mode="t2i", backend="qwen", prompt="A room")).parameters[
            "seed"
        ]
        == 43
    )


def test_explicit_zero_and_legacy_seed_remain_authoritative(session):
    for seed in (0, 42):
        run = create_image_run(session, ImageRequest(mode="t2i", backend="qwen", prompt="A room", seed=seed))
        assert run.parameters["seed"] == seed


@pytest.mark.parametrize("previous,source_seed,expected", [(41, 43, 44), (2**32 - 1, 0, 1)])
def test_correction_seed_also_avoids_source_noise_and_wraps_safely(session, previous, source_seed, expected):
    original = create_image_run(
        session, ImageRequest(mode="t2i", backend="qwen", prompt="A cabinet", seed=source_seed)
    )
    source = Artifact(
        run_id=original.id,
        artifact_type="image",
        relative_path="artifacts/example.png",
        metadata_json={"seed": source_seed},
    )
    session.add(source)
    session.flush()
    assert fresh_seed(session, [source], previous=previous) == expected
