"""CPU clip selection and typed native compatibility; no model or GPU import."""

import hashlib
from uuid import uuid4

import av
import numpy as np
import pytest
from ai_station_runner.video import VideoRequest
from ai_station_runner.wan_motion import continuation_pixels
from pydantic import ValidationError


def clip(tmp_path, count=17):
    path = tmp_path / "source.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=24)
        stream.width = stream.height = 32
        stream.pix_fmt = "yuv420p"
        for index in range(count):
            frame = av.VideoFrame.from_ndarray(
                np.full((32, 32, 3), index * 2, dtype=np.uint8), format="rgb24"
            )
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_single_anchor_is_exact_last_decoded_frame_and_legacy_retains_all_seventeen(tmp_path):
    path, digest = clip(tmp_path)
    with av.open(str(path)) as container:
        expected = [
            frame.to_ndarray(format="rgb24").astype(np.float32) / 255 for frame in container.decode(video=0)
        ]
    anchor = continuation_pixels(path, digest, 32, 32, 1)
    legacy = continuation_pixels(path, digest, 32, 32)
    assert anchor.shape == (1, 32, 32, 3)
    assert legacy.shape == (17, 32, 32, 3)
    np.testing.assert_array_equal(anchor[0], expected[-1])
    np.testing.assert_array_equal(legacy, np.stack(expected))


def test_prefix_rejects_changed_bytes_dimensions_and_insufficient_history(tmp_path):
    path, digest = clip(tmp_path, 1)
    assert continuation_pixels(path, digest, 32, 32, 1).shape[0] == 1
    with pytest.raises(ValueError, match="content changed"):
        continuation_pixels(path, "0" * 64, 32, 32, 1)
    with pytest.raises(ValueError, match="dimensions"):
        continuation_pixels(path, digest, 64, 32, 1)
    with pytest.raises(ValueError, match="required preceding"):
        continuation_pixels(path, digest, 32, 32, 17)


def test_prefix_never_decodes_more_than_one_bounded_segment(tmp_path):
    path, digest = clip(tmp_path, 82)
    with pytest.raises(ValueError, match="native segment size"):
        continuation_pixels(path, digest, 32, 32, 1)


def native_body():
    return {
        "run_id": str(uuid4()),
        "prompt": "Lake",
        "gpu": 0,
        "permissions": ["filesystem_read", "workspace_write"],
    }


def test_native_legacy_identity_and_single_anchor_require_correct_source_kind():
    body = native_body()
    assert "continuation_frames" not in VideoRequest(**body).model_dump(mode="json")
    previous = {"relative_path": "artifacts/previous.mp4", "sha256": "a" * 64, "size_bytes": 100}
    request = VideoRequest(**body, continuation=previous, continuation_frames=1)
    assert request.model_dump(mode="json")["continuation_frames"] == 1
    with pytest.raises(ValidationError, match="preceding video"):
        VideoRequest(**body, continuation_frames=1)
    with pytest.raises(ValidationError, match="without a raw checkpoint"):
        VideoRequest(
            **body,
            continuation=previous,
            continuation_frames=1,
            motion_context={**previous, "relative_path": "artifacts/motion.safetensors"},
        )


@pytest.mark.parametrize("frames", [True, 2, 17.0, "1", 0, 18])
def test_native_prefix_rejects_unknown_or_coerced_counts(frames):
    with pytest.raises(ValidationError):
        VideoRequest(**native_body(), continuation_frames=frames)
