"""CPU memory admission respects the worker container's own cgroup limit."""

from app.control_memory import available_mib


def test_container_headroom_limits_the_larger_physical_memory_observation(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable: 8388608 kB\n")
    (tmp_path / "memory.max").write_text(str(2 * 1024**3))
    (tmp_path / "memory.current").write_text(str(512 * 1024**2))
    assert available_mib(meminfo, tmp_path) == 1536
    (tmp_path / "memory.max").write_text("max")
    assert available_mib(meminfo, tmp_path) == 8192


def test_missing_or_malformed_observation_never_becomes_free_memory(tmp_path):
    meminfo = tmp_path / "meminfo"
    assert available_mib(meminfo, tmp_path) is None
    meminfo.write_text("MemAvailable: unknown kB\n")
    assert available_mib(meminfo, tmp_path) is None
