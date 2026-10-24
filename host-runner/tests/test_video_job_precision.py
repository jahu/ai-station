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
