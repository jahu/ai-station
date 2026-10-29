"""Fresh output expectations preserve old files without following redirects."""

import pytest
from ai_station_runner.validation import ValidationRequest
from ai_station_runner.validation_job import preserve_previous_build
from pydantic import ValidationError


def test_static_output_contract_is_typed_immutable_and_old_requests_still_parse():
    from uuid import uuid4

    old = {
        "run_id": str(uuid4()),
        "project_id": str(uuid4()),
        "worktree_run_id": str(uuid4()),
        "commands": [{"kind": "build", "argv": ["npm", "run", "build"]}],
        "permissions": [],
    }
    previous = ValidationRequest.model_validate(old)
    current = ValidationRequest.model_validate({**old, "output_contract": "static_site"})
    assert previous.output_contract is None and previous != current
    with pytest.raises(ValidationError):
        ValidationRequest.model_validate({**old, "output_contract": "execute_arbitrary_output"})


def test_redirected_previous_build_does_not_touch_target(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    scratch = work / ".scratch"
    scratch.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.html").write_text("Unrelated original")
    (work / "dist").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="ordinary directory"):
        preserve_previous_build(work, scratch)
    assert (work / "dist").is_symlink()
    assert (outside / "index.html").read_text() == "Unrelated original"
    assert not list(scratch.iterdir())
