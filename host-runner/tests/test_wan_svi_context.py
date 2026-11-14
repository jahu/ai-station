"""Metadata-only rejection before an untrusted tensor reaches an inference loader."""

import json
import struct

import pytest
from ai_station_runner.wan_svi_context import METADATA_KEY, SHAPE, validate_checkpoint

PROFILE = "a" * 64
PAYLOAD_BYTES = 16 * 60 * 104 * 4


def checkpoint(tmp_path, *, change=None, metadata=None, extra=False):
    header = {
        "motion": {"dtype": "F32", "shape": list(SHAPE), "data_offsets": [0, PAYLOAD_BYTES]},
        "__metadata__": metadata if metadata is not None else {METADATA_KEY: PROFILE},
    }
    if change:
        header["motion"].update(change)
    if extra:
        header["other"] = dict(header["motion"])
    raw = json.dumps(header).encode()
    path = tmp_path / "motion.safetensors"
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + bytes(PAYLOAD_BYTES))
    return path


def test_svi_context_requires_original_anchor_and_complete_recipe_identity(tmp_path):
    path = checkpoint(tmp_path)
    assert validate_checkpoint(path, PROFILE) == (1, 16, 1, 60, 104)
    with pytest.raises(ValueError, match="profile changed"):
        validate_checkpoint(path, "b" * 64)
    with pytest.raises(ValueError, match="complete frozen"):
        validate_checkpoint(path, "model name")


@pytest.mark.parametrize(
    "change",
    [
        {"dtype": "F16"},
        {"shape": [1, 48, 5, 30, 52]},  # Existing 5B is a different family.
        {"shape": [True, 16, 1, 60, 104]},
        {"shape": [1, 16, 21, 60, 104]},
        {"shape": [1, 16, 1, 104, 60]},  # Portrait is not yet qualified.
        {"data_offsets": [False, PAYLOAD_BYTES]},
        {"data_offsets": [0, PAYLOAD_BYTES - 4]},
        {"data_offsets": [0, PAYLOAD_BYTES, 0]},
        {"unexpected": "input"},
    ],
)
def test_wrong_family_geometry_and_storage_refuse_before_tensor_loading(tmp_path, change):
    with pytest.raises(ValueError, match="geometry"):
        validate_checkpoint(checkpoint(tmp_path, change=change), PROFILE)


@pytest.mark.parametrize(
    "metadata",
    [{"station.wan_profile": PROFILE}, {"station.svi_candidate": PROFILE}, {}, {METADATA_KEY: 123}],
)
def test_legacy_and_private_experimental_context_cannot_be_adopted_as_production(tmp_path, metadata):
    with pytest.raises(ValueError, match="profile"):
        validate_checkpoint(checkpoint(tmp_path, metadata=metadata), PROFILE)


def test_checkpoint_does_not_admit_extra_payload_or_tensors(tmp_path):
    path = checkpoint(tmp_path, extra=True)
    with pytest.raises(ValueError, match="Unexpected tensors"):
        validate_checkpoint(path, PROFILE)
    path = checkpoint(tmp_path)
    path.write_bytes(path.read_bytes() + b"extra bytes")
    with pytest.raises(ValueError, match="geometry"):
        validate_checkpoint(path, PROFILE)


def test_truncated_duplicate_and_unbounded_headers_are_rejected(tmp_path):
    path = checkpoint(tmp_path)
    for data in (
        b"short",
        struct.pack("<Q", 8193),
        struct.pack("<Q", 20) + b"{}",
        struct.pack("<Q", 15) + b'{"x":0,"x":1}  ',
    ):
        path.write_bytes(data)
        with pytest.raises(ValueError):
            validate_checkpoint(path, PROFILE)
    path = checkpoint(tmp_path)
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError):
        validate_checkpoint(path, PROFILE)


def test_symlink_context_is_refused_before_loading(tmp_path):
    path = checkpoint(tmp_path)
    link = tmp_path / "alias.safetensors"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="regular file"):
        validate_checkpoint(link, PROFILE)


def test_portrait_checkpoint_requires_explicit_matching_geometry_without_relabeled_identity(tmp_path):
    from ai_station_runner.wan_svi_context import motion_shape

    portrait = motion_shape(480, 832)
    path = checkpoint(tmp_path, change={"shape": list(portrait)})
    assert validate_checkpoint(path, PROFILE, width=480, height=832) == (1, 16, 1, 104, 60)
    with pytest.raises(ValueError, match="geometry"):
        validate_checkpoint(path, PROFILE)
    with pytest.raises(ValueError, match="profile"):
        validate_checkpoint(path, "b" * 64, width=480, height=832)
    path = checkpoint(tmp_path)
    with pytest.raises(ValueError, match="geometry"):
        validate_checkpoint(path, PROFILE, width=480, height=832)


@pytest.mark.parametrize(
    "dimensions", [(832, 832), (480, 480), (512, 288), (True, 480), (832.0, 480), (480, "832")]
)
def test_context_geometry_cannot_expand_to_an_arbitrary_tensor_budget(tmp_path, dimensions):
    from ai_station_runner.wan_svi_context import motion_shape

    with pytest.raises(ValueError, match="fixed"):
        motion_shape(*dimensions)
    with pytest.raises(ValueError, match="fixed"):
        validate_checkpoint(checkpoint(tmp_path), PROFILE, width=dimensions[0], height=dimensions[1])


@pytest.mark.parametrize(
    "change", [{"dtype": "F16"}, {"shape": [1, 16, 5, 104, 60]}, {"data_offsets": [0, PAYLOAD_BYTES - 4]}]
)
def test_portrait_retains_the_same_bounded_f32_single_motion_contract(tmp_path, change):
    path = checkpoint(tmp_path, change={"shape": [1, 16, 1, 104, 60], **change})
    with pytest.raises(ValueError, match="geometry"):
        validate_checkpoint(path, PROFILE, width=480, height=832)
