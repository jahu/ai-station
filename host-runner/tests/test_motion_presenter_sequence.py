from uuid import uuid4

import pytest
from ai_station_runner.motion_assets import asset_names
from ai_station_runner.motion_codec import check_source
from ai_station_runner.motion_contract import Presenter
from ai_station_runner.motion_document import document
from pydantic import ValidationError
from test_motion_contract import Document, composition, request


def sequence():
    source = {
        "artifact_id": str(uuid4()),
        "kind": "video",
        "relative_path": "artifacts/presenter.mp4",
        "size_bytes": 1,
        "sha256": "a" * 64,
    }
    value = composition(
        scenes=[{"title": "First", "duration_frames": 60}, {"title": "Second", "duration_frames": 90}],
        presenter={
            "clips": [
                {"media": source["artifact_id"], "duration_frames": 61},
                {"media": source["artifact_id"], "duration_frames": 89, "media_start_seconds": 2.04},
            ]
        },
    )
    return value, source


def test_single_presenter_serialization_remains_identical():
    identity = str(uuid4())
    assert Presenter(media=identity).model_dump(mode="json") == {
        "media": identity,
        "placement": "auto",
        "media_start_seconds": 0.0,
    }


def test_contiguous_editorial_intervals_do_not_accumulate_source_fps_rounding():
    value, source = sequence()
    body = request(value, sources=[source])
    assert len(body.sources) == 1
    html, _ = document(value, asset_names(body), audio=True)
    parsed = Document()
    parsed.feed(html)
    videos = [attrs for tag, attrs in parsed.tags if tag == "video"]
    assert len(videos) == 2
    assert videos[0]["data-start"] == "0"
    assert float(videos[0]["data-duration"]) == 61 / 30
    assert float(videos[1]["data-start"]) == 61 / 30
    assert float(videos[1]["data-media-start"]) == 2.04
    assert all("muted" in v and v["data-volume"] == "0" for v in videos)
    assert len([tag for tag, _ in parsed.tags if tag == "audio"]) == 1
    assert "position:absolute;inset:0;display:block" in html
    assert all(f'tl.set("#{video["id"]}"' not in html for video in videos)


@pytest.mark.parametrize(
    "presenter",
    [
        {},
        {"clips": []},
        {"media": str(uuid4()), "clips": [{"media": str(uuid4()), "duration_frames": 150}]},
        {"clips": [{"media": str(uuid4()), "duration_frames": 150}], "media_start_seconds": 1.0},
        {"clips": [{"media": str(uuid4()), "duration_frames": 149}]},
        {"clips": [{"media": str(uuid4()), "duration_frames": True}]},
        {"clips": [{"media": str(uuid4()), "duration_frames": 1801}]},
        {"clips": [{"media": str(uuid4()), "duration_frames": 1}] * 33},
    ],
)
def test_ambiguous_incomplete_or_unbounded_sequences_are_rejected(presenter):
    with pytest.raises(ValidationError):
        composition(scenes=[{"title": "Film", "duration_frames": 150}], presenter=presenter)


def test_native_codec_checks_each_actual_source_window(monkeypatch, tmp_path):
    value, source = sequence()
    body = request(value, sources=[source])
    info = {"streams": [{"codec_type": "video", "width": 512, "height": 640}], "format": {"duration": "5.0"}}
    monkeypatch.setattr("ai_station_runner.motion_codec.probe", lambda *args: info)
    check_source({}, body.sources[0], tmp_path / "face.mp4", body)
    info["format"]["duration"] = "4.9"
    with pytest.raises(ValueError, match="entire film"):
        check_source({}, body.sources[0], tmp_path / "face.mp4", body)
    with pytest.raises(ValidationError, match="presenter"):
        request(value, sources=[{**source, "kind": "image"}])


def test_maximum_scene_and_presenter_sources_fit_one_bounded_ten_minute_film():
    images = [str(uuid4()) for _ in range(60)]
    faces = [str(uuid4()) for _ in range(32)]
    sound = str(uuid4())
    value = composition(
        scenes=[{"duration_frames": 300, "media": media} for media in images],
        presenter={
            "clips": [
                {"media": media, "duration_frames": 562 + (index < 16)} for index, media in enumerate(faces)
            ]
        },
    )
    sources = [
        {
            "artifact_id": identity,
            "kind": kind,
            "relative_path": f"artifacts/{identity}{suffix}",
            "size_bytes": 1,
            "sha256": "a" * 64,
        }
        for identities, kind, suffix in [
            (images, "image", ".png"),
            (faces, "video", ".mp4"),
            ([sound], "audio", ".wav"),
        ]
        for identity in identities
    ]
    body = request(value, sources=sources, audio_artifact_id=sound)
    assert body.composition.frames == 18000 and len(body.sources) == 93
    html, _ = document(value, asset_names(body), audio=True)
    assert 'src="assets/media-91.mp4"' in html
