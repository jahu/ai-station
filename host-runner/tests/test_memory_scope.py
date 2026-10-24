"""Fixed launch parameters and real-kernel checks precede any model import."""

from uuid import uuid4

import pytest
from ai_station_runner import memory_scope


@pytest.mark.parametrize("maximum", [11264, 12288])
def test_fixed_scope_bounds_have_no_caller_selected_systemd_properties(monkeypatch, maximum):
    monkeypatch.setattr(memory_scope.shutil, "which", lambda name: "/usr/bin/systemd-run")
    run_id = str(uuid4())
    argv = memory_scope.scope_prefix(run_id, maximum)
    assert argv[:4] == ["/usr/bin/systemd-run", "--user", "--scope", "--quiet"]
    assert "--unit=ai-station-memory-" + run_id in argv
    assert "--property=MemoryMax=" + str(maximum) + "M" in argv
    assert "--property=MemorySwapMax=0" in argv and "--property=RuntimeMaxSec=3600" in argv
    assert argv[-1] == "--"


@pytest.mark.parametrize("value", [0, True, "11264", 11263, 12289, float("inf")])
def test_unqualified_memory_bounds_never_build_a_launch_command(value):
    with pytest.raises(ValueError, match="explicitly qualified"):
        memory_scope.scope_prefix(str(uuid4()), value)


@pytest.mark.parametrize("value", ["../another-unit", "not-a-uuid", str(uuid4()).upper()])
def test_scope_names_cannot_escape_the_owned_run(value):
    with pytest.raises(ValueError):
        memory_scope.scope_prefix(value, 11264)


def test_missing_user_scope_binary_never_falls_back_to_an_uncapped_process(monkeypatch):
    monkeypatch.setattr(memory_scope.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="unavailable"):
        memory_scope.scope_prefix(str(uuid4()), 11264)


@pytest.mark.parametrize("fault", [None, "wrong-unit", "unlimited-ram", "different-ram", "swap", "missing"])
def test_kernel_guard_requires_the_actual_owned_scope_and_both_limits(tmp_path, monkeypatch, fault):
    run_id = str(uuid4())
    group = tmp_path / (
        memory_scope.scope_name(run_id) + ".scope" if fault != "wrong-unit" else "another.scope"
    )
    group.mkdir()
    (group / "memory.max").write_text(
        "max" if fault == "unlimited-ram" else str((12288 if fault == "different-ram" else 11264) * 1024**2)
    )
    (group / "memory.swap.max").write_text("1024" if fault == "swap" else "0")
    if fault == "missing":
        (group / "memory.max").unlink()
    monkeypatch.setattr(memory_scope, "current_group", lambda: group)
    if fault:
        with pytest.raises(ValueError):
            memory_scope.require_scope(run_id, 11264)
    else:
        assert memory_scope.require_scope(run_id, 11264) == {"maximum_ram_mib": 11264, "maximum_swap_mib": 0}
