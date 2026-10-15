"""Bounded signatures only. Actual compressed-audio validation belongs to the worker."""

MAX_BYTES = 20 * 1024 * 1024
FORMATS = {
    "wav": ("audio/wav", ".wav"),
    "mp3": ("audio/mpeg", ".mp3"),
    "mov": ("audio/mp4", ".m4a"),
    "ogg": ("audio/ogg", ".ogg"),
    "matroska": ("audio/webm", ".webm"),
    "flac": ("audio/flac", ".flac"),
}


def recording_format(data):
    if not 12 <= len(data) <= MAX_BYTES:
        raise ValueError("Use a recording up to 20 MiB")
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:3] == b"ID3" or (
        data[0] == 255
        and data[1] & 224 == 224
        and data[1] & 6 == 2
        and data[1] & 24 != 8
        and data[2] & 12 != 12
    ):
        return "mp3"
    if data[4:8] == b"ftyp":
        return "mov"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "matroska"
    if data[:4] == b"fLaC":
        return "flac"
    raise ValueError("Use WAV, MP3, M4A, Ogg, WebM or FLAC audio; playlists and URLs are not recordings")
