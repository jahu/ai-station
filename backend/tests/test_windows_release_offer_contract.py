"""Windows publisher admission shares the control-plane fingerprint contract."""

import json
from pathlib import Path

from ai_station_runner.station_release_metadata import admit_release


def test_windows_powershell_fixture_matches_the_shared_release_authority():
    source = Path(__file__).resolve().parents[2] / "packaging/windows/tests/fixtures/release-offer.json"
    fixture = json.loads(source.read_text())
    assert admit_release(fixture["raw"]) == fixture["expected"]
