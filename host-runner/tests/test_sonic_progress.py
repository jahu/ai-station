import json
from uuid import uuid4

import pytest
from ai_station_runner.sonic_progress import Progress


@pytest.mark.parametrize("base,windows", [(9, 25), (25, 25), (26, 50), (501, 525), (750, 750)])
def test_progress_counts_actual_global_windows_and_preserves_native_values(tmp_path, base, windows):
    run_id, recipe = str(uuid4()), {"id": "sonic_whole_768_v1", "observation": "c" * 64}
    progress = Progress(tmp_path, run_id, recipe, base)
    values = {"latents": object()}
    for completed in range(windows):
        assert progress.advance(None, completed // progress.windows_per_step, None, values) is values
    progress.finishing()
    assert json.loads((tmp_path / "progress.json").read_text()) == {
        "version": 1,
        "run_id": run_id,
        "recipe": recipe,
        "phase": "finishing",
        "completed_windows": windows,
        "total_windows": windows,
    }
    assert (tmp_path / "progress.json").stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "progress.tmp").exists()


def test_missing_or_reordered_model_calls_cannot_claim_complete_generation(tmp_path):
    progress = Progress(tmp_path, str(uuid4()), {}, 501)
    with pytest.raises(ValueError, match="every global"):
        progress.finishing()
    with pytest.raises(ValueError, match="frozen global"):
        progress.advance(None, 1, None, {})
    assert progress.completed == 0
