"""Public origins are exact observations, not private recipe/run projections."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from app.model_provenance import publisher_source
from app.setup_models import CANDIDATES


def observed():
    source = {
        "repository": "publisher/new-model",
        "revision": "a" * 40,
        "filename": "Q4/new-model.gguf",
        "license": "apache-2.0",
        "file": {"sha256": "b" * 64, "size_bytes": 123},
        "source_url": "https://private.invalid/?credential=never-return",
        "private_run_id": "never-return",
        "secret_ref": "never-return",
    }
    return SimpleNamespace(metadata_json={"source": source}), SimpleNamespace(sha256="b" * 64, size_bytes=123)


def test_public_origin_is_canonical_and_does_not_forward_recipe_secrets_or_mutate_metadata():
    definition, file = observed()
    original = deepcopy(definition.metadata_json)
    result = publisher_source(definition, file)
    assert (
        result["pinned_url"]
        == "https://huggingface.co/publisher/new-model/blob/" + "a" * 40 + "/Q4/new-model.gguf"
    )
    assert result["review_url"] == "https://huggingface.co/publisher/new-model/blob/main/Q4/new-model.gguf"
    assert "never-return" not in str(result) and "secret_ref" not in result
    assert definition.metadata_json == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository", "../escape"),
        ("repository", "https://evil.invalid/model"),
        ("revision", "main"),
        ("filename", "../model.gguf"),
        ("filename", "x\\model.gguf"),
        ("filename", "file%2fescape.gguf"),
        ("file", {"sha256": "c" * 64, "size_bytes": 123}),
        ("file", {"sha256": "b" * 64, "size_bytes": True}),
    ],
)
def test_malformed_or_changed_coordinates_have_no_invented_publisher(field, value):
    definition, file = observed()
    definition.metadata_json["source"][field] = value
    assert publisher_source(definition, file) is None


def test_only_an_exact_older_curated_object_can_recover_a_known_origin():
    entry = CANDIDATES[0]
    definition = SimpleNamespace(metadata_json={"catalog_id": entry.id})
    file = SimpleNamespace(sha256=entry.file.sha256, size_bytes=entry.file.size_bytes)
    result = publisher_source(definition, file)
    assert result["repository"] == entry.repository and result["revision"] == entry.revision
    file.size_bytes += 1
    assert publisher_source(definition, file) is None
    definition.metadata_json = {"catalog_id": "unknown"}
    assert publisher_source(definition, file) is None
