import hashlib
from html.parser import HTMLParser
from uuid import uuid4

import pytest
from ai_station_runner.motion_codec import check_source
from ai_station_runner.motion_contract import Composition, MotionRequest, Source
from ai_station_runner.motion_document import colors, contrast, document
from ai_station_runner.motion_job import copy_source
from pydantic import ValidationError


def composition(**extra):
    return Composition.model_validate(
        {
            "style": {"palette": ["#663399", "#101218", "#FCFCFF"], "brand": "Learning studio"},
            "scenes": [{"title": "A clear first idea", "duration_frames": 90}],
            **extra,
        }
    )


def request(value=None, **extra):
    return MotionRequest.model_validate(
        {
            "run_id": str(uuid4()),
            "deadline_at": 1900000000.0,
            "composition": (value or composition()).model_dump(mode="json"),
            "observation": "a" * 64,
            "permissions": ["filesystem_read", "workspace_write"],
            **extra,
        }
    )


@pytest.mark.parametrize(
    "change",
    [
        {"width": 1920, "height": 1920},
        {"fps": 60},
        {"style": {"palette": ["url(https://example.org)"]}},
        {"style": {"palette": ["#123456"], "typography": "javascript"}},
        {"scenes": [{"title": "Invalid", "duration_frames": True}]},
        {"scenes": [{"title": "Invalid", "duration_frames": 0}]},
        {"scenes": [{"duration_frames": 90}]},
        {"scenes": [{"title": "Invalid", "duration_frames": 90, "media_start_seconds": float("nan")}]},
        {"scenes": [{"title": "Invalid", "duration_frames": 90, "media": "/etc/passwd"}]},
        {"scenes": [{"title": "Invalid", "duration_frames": 90, "script": "alert(1)"}]},
        {"scenes": [{"layout": "full_bleed", "title": "No real image", "duration_frames": 90}]},
        {"scenes": [{"title": "Too long", "duration_frames": 2700}] * 7},
    ],
)
def test_invalid_motion_intent_cannot_become_executable_content(change):
    with pytest.raises(ValidationError):
        composition(**change)


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.images = [], []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.tags.append((tag, values))
        if tag == "script":
            self.scripts.append(values)
        if tag in {"img", "video", "audio"}:
            self.images.append(values)


def test_markup_and_untrusted_urls_stay_text_in_every_editorial_field():
    hostile = '</script><script src="https://example.org/steal"></script><img src="file:///etc/passwd">'
    value = composition(
        style={"palette": ["#336699"], "brand": hostile},
        scenes=[
            {
                "duration_frames": 90,
                "title": hostile,
                "body": hostile,
                "eyebrow": hostile[:80],
                "points": [hostile],
                "metrics": [{"value": "<script>", "label": hostile}],
            }
        ],
    )
    body, _ = document(value)
    parsed = Document()
    parsed.feed(body)
    assert parsed.images == []
    assert len(parsed.scripts) == 2
    assert parsed.scripts[0] == {"src": "assets/gsap.min.js"}
    assert all(not key.startswith("on") for _, attrs in parsed.tags for key in attrs)
    assert "&lt;/script&gt;" in body


def test_dark_and_light_identites_keep_readable_text_without_rewriting_the_saved_palette():
    for palette in (["#808080", "#FFFFFF", "#FFFF00"], ["#111111", "#000000", "#101010"]):
        value = composition(style={"palette": palette})
        adjusted = colors(value.style)
        assert contrast(adjusted["foreground"], adjusted["background"]) >= 4.5
        assert contrast(adjusted["accent_ink"], adjusted["background"]) >= 3
        assert value.style.palette == palette


def test_visual_binding_is_an_owned_uuid_not_a_model_supplied_path():
    asset = uuid4()
    value = composition(
        scenes=[
            {"layout": "full_bleed", "duration_frames": 90, "media": str(asset), "media_motion": "pan_left"}
        ]
    )
    for path in ["https://example.org/image.png", "file:///etc/passwd", "assets/../outside.png"]:
        with pytest.raises(ValueError, match="frozen owned"):
            document(value, {str(asset): path})
    body, _ = document(value, {str(asset): "assets/media-0.png"})
    parsed = Document()
    parsed.feed(body)
    assert len(parsed.images) == 1 and parsed.images[0]["src"] == "assets/media-0.png"


def test_source_bindings_cannot_sneak_in_unrequested_media_or_permissions():
    fake = {
        "artifact_id": str(uuid4()),
        "kind": "image",
        "relative_path": "artifacts/example.png",
        "size_bytes": 1,
        "sha256": "a" * 64,
    }
    with pytest.raises(ValidationError, match="exactly"):
        request(sources=[fake])
    with pytest.raises(ValidationError):
        request(permissions=["filesystem_read", "network_external"])
    with pytest.raises(ValidationError):
        request(permissions=["filesystem_read", "filesystem_read"])
    asset = uuid4()
    value = composition(scenes=[{"duration_frames": 90, "media": str(asset)}])
    with pytest.raises(ValidationError, match="exactly"):
        request(value)
    with pytest.raises(ValidationError, match="exactly"):
        request(value, sources=[{**fake, "artifact_id": str(asset)}] * 2)
    with pytest.raises(ValidationError, match="visuals"):
        request(value, sources=[{**fake, "artifact_id": str(asset), "kind": "audio"}])


def source(tmp_path, data=b"original bytes"):
    path = tmp_path / "artifacts/source.png"
    path.parent.mkdir()
    path.write_bytes(data)
    return path, Source(
        artifact_id=uuid4(),
        kind="image",
        relative_path="artifacts/source.png",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def test_copy_rechecks_bytes_and_rejects_symlinks_and_hardlinks(tmp_path):
    path, frozen = source(tmp_path)
    copy_source(tmp_path, frozen, tmp_path / "copied.png")
    assert (tmp_path / "copied.png").read_bytes() == b"original bytes"
    path.write_bytes(b"different data")
    with pytest.raises(ValueError):
        copy_source(tmp_path, frozen, tmp_path / "changed.png")
    path.unlink()
    other = tmp_path / "other.png"
    other.write_bytes(b"original bytes")
    path.symlink_to(other)
    with pytest.raises((ValueError, OSError)):
        copy_source(tmp_path, frozen, tmp_path / "symlink.png")
    path.unlink()
    path.hardlink_to(other)
    with pytest.raises(ValueError, match="regular file"):
        copy_source(tmp_path, frozen, tmp_path / "hardlink.png")


def test_timing_uses_actual_source_coverage_instead_of_freezing_or_looping_video(tmp_path, monkeypatch):
    _, frozen = source(tmp_path)
    frozen.kind = "video"
    value = composition(
        scenes=[{"duration_frames": 90, "media": str(frozen.artifact_id), "media_start_seconds": 1.0}]
    )
    body = request(value, sources=[frozen.model_dump(mode="json")])
    monkeypatch.setattr(
        "ai_station_runner.motion_codec.probe",
        lambda *a: {
            "streams": [{"codec_type": "video", "width": 1280, "height": 704}],
            "format": {"duration": "3.0"},
        },
    )
    with pytest.raises(ValueError, match="actual source video"):
        check_source({}, frozen, tmp_path / "source.mp4", body)


def test_soundtrack_must_cover_all_frames_and_have_the_canonical_mix_format(tmp_path, monkeypatch):
    _, frozen = source(tmp_path)
    frozen.kind = "audio"
    body = request(sources=[frozen.model_dump(mode="json")], audio_artifact_id=str(frozen.artifact_id))

    def probe(*a):
        return {
            "streams": [
                {"codec_type": "audio", "codec_name": "pcm_s16le", "sample_rate": "48000", "channels": 2}
            ],
            "format": {"duration": "2.0"},
        }

    monkeypatch.setattr("ai_station_runner.motion_codec.probe", probe)
    with pytest.raises(ValueError, match="complete material"):
        check_source({}, frozen, tmp_path / "mix.wav", body)


def test_nested_video_owns_absolute_timing_without_a_timed_wrapper():
    asset = uuid4()
    value = composition(
        scenes=[
            {"title": "Opening", "duration_frames": 60},
            {"title": "Footage", "duration_frames": 90, "media": str(asset), "media_start_seconds": 1.0},
        ]
    )
    body, _ = document(value, {str(asset): "assets/media-0.mp4"})
    parsed = Document()
    parsed.feed(body)
    sections = [attrs for tag, attrs in parsed.tags if tag == "section"]
    assert all("data-start" not in attrs and "clip" not in attrs["class"].split() for attrs in sections)
    assert sections[1]["data-scene-start"] == "2.0"
    assert parsed.images[0]["data-start"] == "2.0"
    assert parsed.images[0]["data-media-start"] == "1.0"
    assert 'visibility:"hidden"},2.0' in body
