"""The private qualification does not expose arbitrary Comfy loader options."""

import json
import sys

import pytest
from ai_station_runner.video_job import main


@pytest.mark.parametrize("precision", ["fp8_e4m3fn_fast", "fp8_e5m2", "arbitrary", None, [], True])
def test_unapproved_job_precision_is_rejected_before_importing_or_loading_comfy(tmp_path, precision):
    path = tmp_path / "request.json"
    path.write_text(json.dumps({"request": {"weight_dtype": precision}, "paths": {}, "work": str(tmp_path)}))
    modules = set(sys.modules)
    with pytest.raises(ValueError, match="Unsupported fixed Wan weight precision"):
        main(path)
    assert not {name for name in set(sys.modules) - modules if name == "torch" or name.startswith("comfy")}


def test_unqualified_precision_is_not_exposed_through_native_video_requests():
    from uuid import uuid4

    from ai_station_runner.video import VideoRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as error:
        VideoRequest.model_validate(
            {
                "run_id": str(uuid4()),
                "prompt": "Unqualified option",
                "gpu": 7,
                "permissions": ["filesystem_read", "workspace_write"],
                "weight_dtype": "fp8_e4m3fn",
            }
        )
    assert any(
        item["type"] == "extra_forbidden" and item["loc"] == ("weight_dtype",)
        for item in error.value.errors()
    )
