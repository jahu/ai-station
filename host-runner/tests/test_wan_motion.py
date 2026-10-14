import json
import struct

import pytest
from ai_station_runner.wan_motion import validate_checkpoint


def checkpoint(tmp_path, **changes):
    shape = [1, 48, 5, 8, 8]
    size = 48 * 5 * 8 * 8 * 4
    header = {
        "motion": {"dtype": "F32", "shape": shape, "data_offsets": [0, size]},
        "__metadata__": {"station.wan_profile": "profile"},
    }
    header["motion"].update(changes)
    raw = json.dumps(header).encode()
    path = tmp_path / "motion.safetensors"
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\0" * size)
    return path


def test_motion_header_only_accepts_one_bounded_tensor_for_same_profile(tmp_path):
    path = checkpoint(tmp_path)
    assert validate_checkpoint(path, 128, 128, "profile") == [1, 48, 5, 8, 8]
    with pytest.raises(ValueError, match="observation"):
        validate_checkpoint(path, 128, 128, "other-model")


@pytest.mark.parametrize(
    "changes",
    [
        {"dtype": "F64"},
        {"shape": [1, 48, 500000, 8, 8]},
        {"data_offsets": [0, 0]},
        {"shape": [True, 48, 5, 8, 8]},
    ],
)
def test_motion_rejects_type_shape_or_payload_changes(tmp_path, changes):
    with pytest.raises(ValueError):
        validate_checkpoint(checkpoint(tmp_path, **changes), 128, 128, "profile")


def test_motion_rejects_excessive_header_and_truncation(tmp_path):
    path = checkpoint(tmp_path)
    path.write_bytes(struct.pack("<Q", 9999999) + b"bad")
    with pytest.raises(ValueError, match="header"):
        validate_checkpoint(path, 128, 128, "profile")
    path = checkpoint(tmp_path)
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match="observation"):
        validate_checkpoint(path, 128, 128, "profile")
