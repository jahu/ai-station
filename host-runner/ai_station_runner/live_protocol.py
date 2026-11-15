"""Closed live media framing shared by the native broker and inference children.

Packets contain no paths, commands or model choices. Media is ephemeral; callers
must authenticate a session before accepting packets and bound its input queues.
"""

import array
import math
import struct
import sys
from dataclasses import dataclass
from enum import IntEnum

MAGIC = b"AISL"
VERSION = 1
HEADER = struct.Struct("!4sBBIQ")
MAX_IMAGE_BYTES = 512 * 1024
SAMPLE_RATE = 22050
BLOCK_SAMPLES = 4410
AUDIO_BYTES = BLOCK_SAMPLES * 4
MAX_TIMESTAMP_US = 4 * 60 * 60 * 1_000_000


class Kind(IntEnum):
    CAMERA = 1
    MICROPHONE = 2
    PICTURE = 17
    SPEECH = 18


@dataclass(frozen=True)
class Packet:
    kind: Kind
    sequence: int
    timestamp_us: int
    body: bytes


def decode(raw: bytes, *, incoming: bool) -> Packet:
    if not isinstance(raw, bytes) or not HEADER.size < len(raw) <= HEADER.size + MAX_IMAGE_BYTES:
        raise ValueError("Live packet size is invalid")
    magic, version, kind, sequence, timestamp = HEADER.unpack_from(raw)
    if magic != MAGIC or version != VERSION or timestamp > MAX_TIMESTAMP_US:
        raise ValueError("Live packet header is invalid")
    allowed = (Kind.CAMERA, Kind.MICROPHONE) if incoming else (Kind.PICTURE, Kind.SPEECH)
    if kind not in allowed:
        raise ValueError("Live packet direction or type is invalid")
    body = raw[HEADER.size :]
    if kind in (Kind.MICROPHONE, Kind.SPEECH):
        if len(body) != AUDIO_BYTES:
            raise ValueError("Live audio must contain one fixed mono PCM block")
        values = array.array("f")
        values.frombytes(body)
        if sys.byteorder != "little":
            values.byteswap()
        if any(not math.isfinite(value) or abs(value) > 1.0 for value in values):
            raise ValueError("Live audio must contain finite normalized samples")
    elif not body.startswith(b"\xff\xd8\xff") or not body.endswith(b"\xff\xd9"):
        raise ValueError("Live camera packets must contain a bounded JPEG")
    return Packet(Kind(kind), sequence, timestamp, body)


def encode(packet: Packet) -> bytes:
    # Validate outbound data as strictly as inbound data; a bad inference result
    # cannot inject another packet type or an unbounded payload into the proxy.
    try:
        raw = (
            HEADER.pack(MAGIC, VERSION, int(packet.kind), packet.sequence, packet.timestamp_us) + packet.body
        )
    except (ValueError, TypeError, struct.error, OverflowError) as exc:
        raise ValueError("Live packet fields are invalid") from exc
    decode(raw, incoming=packet.kind in (Kind.CAMERA, Kind.MICROPHONE))
    return raw


class StreamOrder:
    """Independent clocks per medium, retained for a session across reconnects."""

    def __init__(self):
        self._last: dict[Kind, tuple[int, int]] = {}

    def accept(self, packet: Packet) -> None:
        previous = self._last.get(packet.kind)
        if previous is not None:
            sequence, timestamp = previous
            if packet.sequence <= sequence or packet.timestamp_us <= timestamp:
                raise ValueError("Replayed or reordered live packet")
            if packet.kind in (Kind.MICROPHONE, Kind.SPEECH):
                if packet.sequence != sequence + 1 or packet.timestamp_us != timestamp + 200_000:
                    raise ValueError("Live audio clock has a gap; restart rather than accumulate drift")
        self._last[packet.kind] = (packet.sequence, packet.timestamp_us)
