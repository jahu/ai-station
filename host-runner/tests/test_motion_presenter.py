from uuid import uuid4

import pytest
from ai_station_runner.motion_codec import check_source
from ai_station_runner.motion_document import document
from pydantic import ValidationError
from test_motion_contract import Document, composition, request


def setup(**extra):
    identity = str(uuid4())
    value = composition(
        scenes=[{"title": "Opening", "duration_frames": 60}, {"title": "Next", "duration_frames": 90}],
        presenter={"media": identity, "media_start_seconds": 1.0},
        **extra,
    )
    source = dict(
        artifact_id=identity,
        kind="video",
        relative_path="artifacts/presenter.mp4",
        size_bytes=100,
        sha256="a" * 64,
    )
    return value, source


def test_unused_presenter_preserves_legacy_request_digest():
    value = composition()
    original = value.model_dump(mode="json")
    assert "presenter" not in original
    assert composition(presenter=None).model_dump(mode="json") == original


@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080), (1080, 1080)])
def test_one_muted_presenter_covers_the_whole_timeline(size):
    value, source = setup(width=size[0], height=size[1])
    body = request(value, sources=[source])
    html, _ = document(body.composition, {source["artifact_id"]: "assets/media-0.mp4"}, audio=True)
    parsed = Document()
    parsed.feed(html)
    videos = [attrs for tag, attrs in parsed.tags if tag == "video"]
    assert len(videos) == 1
    assert videos[0]["id"] == "presenter"
    assert videos[0]["data-start"] == "0"
    assert videos[0]["data-duration"] == "5.0"
    assert videos[0]["data-media-start"] == "1.0"
    assert videos[0]["data-volume"] == "0" and "muted" in videos[0]
    assert len([tag for tag, _ in parsed.tags if tag == "audio"]) == 1
    assert 'class="story-stage"' in html
    assert "object-fit:contain" in html


def test_presenter_sources_are_exact_video_bindings_and_may_be_shared_with_a_scene():
    value, source = setup()
    with pytest.raises(ValidationError, match="exactly"):
        request(value)
    with pytest.raises(ValidationError, match="presenter"):
        request(value, sources=[{**source, "kind": "image"}])
    value.scenes[0].media = value.presenter.media
    assert len(request(value, sources=[source]).sources) == 1
    with pytest.raises(ValidationError, match="exactly"):
        request(value, sources=[source, source])
    for path in ["https://example.com/a.mp4", "assets/../outside.mp4", "assets/media-0.png"]:
        with pytest.raises(ValueError, match="frozen owned"):
            document(value, {source["artifact_id"]: path})


@pytest.mark.parametrize(
    "field,value",
    [
        ("placement", "overlay"),
        ("css", "position:fixed"),
        ("media_start_seconds", float("nan")),
        ("media_start_seconds", -1.0),
    ],
)
def test_presenter_cannot_inject_layout_or_unbounded_timing(field, value):
    board, _ = setup()
    raw = board.model_dump(mode="json")
    raw["presenter"][field] = value
    with pytest.raises(ValidationError):
        composition(**raw)


def test_actual_decode_duration_must_cover_presenter_through_the_last_scene(monkeypatch, tmp_path):
    value, source = setup()
    body = request(value, sources=[source])
    info = {"streams": [{"codec_type": "video", "width": 512, "height": 512}], "format": {"duration": "5.0"}}
    monkeypatch.setattr("ai_station_runner.motion_codec.probe", lambda *args: info)
    with pytest.raises(ValueError, match="entire film"):
        check_source({}, body.sources[0], tmp_path / "clip.mp4", body)
    info["format"]["duration"] = "6.0"
    check_source({}, body.sources[0], tmp_path / "clip.mp4", body)
