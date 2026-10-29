"""Real CPU container verification and fail-closed native candidate entry."""

from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import av
import pytest
from ai_station_runner import memory_scope, sonic_entry


def movie(path, *, count=18, fps=25, audio=True, audio_samples=16321, gap=False):
    with av.open(str(path), "w") as container:
        video = container.add_stream("libx264", rate=fps)
        video.width = video.height = 192
        video.pix_fmt = "yuv420p"
        if audio:
            stream = container.add_stream("aac", rate=24000)
            stream.layout = "mono"
        for index in range(count):
            frame = av.VideoFrame(192, 192, "yuv420p")
            for plane in frame.planes:
                plane.update(b"\x80" * plane.buffer_size)
            frame.pts = index * (2 if gap else 1)
            frame.time_base = Fraction(1, fps)
            for packet in video.encode(frame):
                container.mux(packet)
        for packet in video.encode():
            container.mux(packet)
        if audio:
            frame = av.AudioFrame(format="fltp", layout="mono", samples=audio_samples)
            frame.sample_rate = 24000
            frame.pts, frame.time_base = 0, Fraction(1, 24000)
            for plane in frame.planes:
                plane.update(b"\x00" * plane.buffer_size)
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)


def observation(**changes):
    return {
        "width": 192,
        "height": 192,
        "channels": 1,
        "sample_rate": 24000,
        "samples": 16321,
        "target_frames": 18,
        **changes,
    }


def test_output_verifier_decodes_the_complete_real_movie_and_non_integral_speech(tmp_path):
    path = tmp_path / "complete.mp4"
    movie(path)
    sonic_entry.verify_movie(path, observation())


@pytest.mark.parametrize(
    "change",
    [
        {"count": 17},
        {"count": 19},
        {"fps": 24},
        {"gap": True},
        {"audio": False},
        {"audio_samples": 12000},
        {"audio_samples": 24000},
    ],
)
def test_missing_speech_frames_or_invalid_timing_are_not_successful_outputs(tmp_path, change):
    path = tmp_path / "invalid.mp4"
    movie(path, **change)
    with pytest.raises(ValueError):
        sonic_entry.verify_movie(path, observation())


@pytest.mark.parametrize("change", [{"width": 256}, {"height": 256}, {"channels": 2}, {"samples": 24000}])
def test_output_must_match_the_frozen_portrait_and_canonical_audio_observation(tmp_path, change):
    path = tmp_path / "changed.mp4"
    movie(path)
    with pytest.raises(ValueError):
        sonic_entry.verify_movie(path, observation(**change))


def test_candidate_entry_requires_opt_in_before_importing_model_dependencies(monkeypatch):
    monkeypatch.delenv("AI_STATION_REAL_GPU_TESTS", raising=False)
    with pytest.raises(ValueError, match="explicit real-GPU opt-in"):
        sonic_entry.qualification_scope(str(uuid4()))


def test_opt_in_alone_does_not_authorize_unbounded_gpu_execution(monkeypatch):
    monkeypatch.setenv("AI_STATION_REAL_GPU_TESTS", "1")
    with pytest.raises(ValueError, match="outside its owned memory scope"):
        sonic_entry.qualification_scope(str(uuid4()))


def test_qualification_requires_the_actual_kernel_ram_and_zero_swap_limits(tmp_path, monkeypatch):
    run_id = str(uuid4())
    group = tmp_path / (memory_scope.scope_name(run_id) + ".scope")
    group.mkdir()
    (group / "memory.max").write_text(str(18432 * 1024**2))
    (group / "memory.swap.max").write_text("0")
    monkeypatch.setattr(memory_scope, "current_group", lambda: group)
    monkeypatch.setenv("AI_STATION_REAL_GPU_TESTS", "1")
    assert sonic_entry.qualification_scope(run_id) == {"maximum_ram_mib": 18432, "maximum_swap_mib": 0}
    (group / "memory.swap.max").write_text("1024")
    with pytest.raises(ValueError, match="zero-swap"):
        sonic_entry.qualification_scope(run_id)


def test_whole_candidate_uses_only_the_fixed_extended_scope_fuse(monkeypatch):
    monkeypatch.setattr(memory_scope.shutil, "which", lambda name: "/usr/bin/systemd-run")
    argv = memory_scope.scope_prefix(str(uuid4()), 18432)
    assert "--property=MemoryMax=18432M" in argv
    assert "--property=MemorySwapMax=0" in argv
    assert "--property=RuntimeMaxSec=14400" in argv
    assert argv[-1] == "--"
    for original in (11264, 12288):
        assert "--property=RuntimeMaxSec=3600" in memory_scope.scope_prefix(str(uuid4()), original)


def test_fixed_entry_denies_network_connectors_and_user_imported_model_fetches():
    with pytest.raises(RuntimeError, match="runs offline"):
        sonic_entry.deny_network(("example.invalid", 443))


def test_native_modules_retain_the_model_python_syntax_version():
    import ast

    package = Path(sonic_entry.__file__).parent
    for name in ("sonic_contract", "sonic_entry", "sonic_frames", "sonic_guidance", "sonic_inference"):
        ast.parse((package / (name + ".py")).read_text(), feature_version=(3, 10))
