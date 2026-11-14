import array
import struct
import sys

import pytest
from ai_station_runner.live_protocol import (
    AUDIO_BYTES,
    BLOCK_SAMPLES,
    HEADER,
    MAGIC,
    MAX_IMAGE_BYTES,
    Kind,
    Packet,
    StreamOrder,
    decode,
    encode,
)


def pcm(value=0.0):
    samples = array.array("f", [value] * BLOCK_SAMPLES)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def test_audio_and_video_have_separate_ordered_clocks_and_fixed_frames():
    order = StreamOrder()
    for i in range(3):
        packet = Packet(Kind.MICROPHONE, i, i * 200_000, pcm(0.3))
        assert decode(encode(packet), incoming=True) == packet
        order.accept(packet)
        order.accept(Packet(Kind.CAMERA, i, i * 33_333, b"\xff\xd8\xff\xe0\xff\xd9"))
    assert len(packet.body) == AUDIO_BYTES


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 1.01, -1.01])
def test_nonfinite_or_clipping_audio_is_rejected(value):
    with pytest.raises(ValueError, match="finite normalized"):
        encode(Packet(Kind.MICROPHONE, 1, 200_000, pcm(value)))


@pytest.mark.parametrize("kind", [Kind.CAMERA, Kind.MICROPHONE, 255])
def test_inbound_packets_cannot_be_injected_as_transformed_output(kind):
    body = pcm() if kind == Kind.MICROPHONE else b"\xff\xd8\xff\xe0\xff\xd9"
    raw = HEADER.pack(MAGIC, 1, kind, 0, 0) + body
    with pytest.raises(ValueError, match="direction or type"):
        decode(raw, incoming=False)


@pytest.mark.parametrize(
    "raw",
    [
        b"short",
        HEADER.pack(b"BAD!", 1, Kind.CAMERA, 1, 1) + b"a",
        HEADER.pack(MAGIC, 9, Kind.CAMERA, 1, 1) + b"a",
        HEADER.pack(MAGIC, 1, Kind.CAMERA, 1, 4 * 60 * 60 * 1_000_000 + 1) + b"a",
        HEADER.pack(MAGIC, 1, Kind.CAMERA, 1, 1) + b"x" * (MAX_IMAGE_BYTES + 1),
        HEADER.pack(MAGIC, 1, Kind.CAMERA, 1, 1) + b"\xff\xd8\xfftruncated",
        HEADER.pack(MAGIC, 1, Kind.MICROPHONE, 1, 1) + pcm()[:-4],
    ],
)
def test_invalid_framing_and_incomplete_media_are_rejected(raw):
    with pytest.raises(ValueError):
        decode(raw, incoming=True)


@pytest.mark.parametrize("sequence,timestamp", [(0, 200_000), (1, 0), (2, 200_000), (1, 200_001)])
def test_replay_audio_loss_and_drift_require_restart(sequence, timestamp):
    order = StreamOrder()
    order.accept(Packet(Kind.MICROPHONE, 0, 0, pcm()))
    with pytest.raises(ValueError):
        order.accept(Packet(Kind.MICROPHONE, sequence, timestamp, pcm()))


def test_output_is_bounded_and_validated_before_transmission():
    packet = Packet(Kind.SPEECH, 1, 200_000, pcm(-0.2))
    assert decode(encode(packet), incoming=False) == packet
    with pytest.raises(ValueError):
        encode(Packet(Kind.SPEECH, 1, 200_000, pcm() + b"extra"))
    with pytest.raises(ValueError):
        encode(Packet(Kind.PICTURE, -1, 0, b"\xff\xd8\xff\xe0\xff\xd9"))
    with pytest.raises(struct.error):
        HEADER.pack(MAGIC, 1, Kind.PICTURE, 2**32, 0)
