import pytest
from app.recordings import FORMATS, recording_format


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"ID3" + b"\0" * 20, "mp3"),
        (b"\xff\xfb\x90\0" + b"\0" * 20, "mp3"),
        (b"\0\0\0\x18ftypM4A " + b"\0" * 20, "mov"),
        (b"OggS" + b"\0" * 30, "ogg"),
        (b"\x1aE\xdf\xa3" + b"\0" * 20, "matroska"),
        (b"fLaC" + b"\0" * 20, "flac"),
    ],
)
def test_allowlisted_container_signatures(data, expected):
    from ai_station_runner.recordings import recording_format as native_format

    assert recording_format(data) == native_format(data) == expected
    assert FORMATS[expected][0].startswith("audio/")


@pytest.mark.parametrize(
    "data",
    [
        b"#EXTM3U\nhttps://example.com/a.mp3",
        b"ffconcat version 1.0\nfile /etc/passwd",
        b'<?xml version="1.0"?><MPD>',
        b"https://example.com/recording.mp3",
        b"PK\x03\x04" + b"\0" * 20,
        b"\xff\xf1\x90\0" + b"\0" * 20,
    ],
)
def test_playlists_urls_and_non_recordings_are_rejected_at_both_boundaries(data):
    from ai_station_runner.recordings import recording_format as native_format

    for boundary in (recording_format, native_format):
        with pytest.raises(ValueError):
            boundary(data)


@pytest.mark.parametrize(
    "rate,channels,samples,elapsed",
    [
        (192000, 1, 1024, 0),
        (48000, 6, 1024, 0),
        (16000, 1, 160001, 0),
        (16000, 1, 16000, 300),
        (0, 1, 1024, 0),
        (16000, 1, 0, 0),
    ],
)
def test_decoded_frame_budgets_fail_before_conversion(rate, channels, samples, elapsed):
    from ai_station_runner.recordings import frame_budget as native_budget

    with pytest.raises(ValueError):
        native_budget(rate, channels, samples, elapsed)


def test_secondary_decoder_io_is_always_denied():
    from ai_station_runner.transcription_decode import deny_external_io

    for url in (
        "https://example.com/private",
        "http://127.0.0.1:8765/api",
        "file:///etc/passwd",
        "/etc/passwd",
        "../other.wav",
    ):
        with pytest.raises(PermissionError):
            deny_external_io(url, 0, {})
