"""Pure observations from actual native log formats; never invoke inference."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from app.db import utcnow
from app.generation_progress import active_progress, observe, parse_line, projection


@pytest.fixture(autouse=True)
def isolated_db():
    # These parser/projection cases deliberately require no database or migration.
    yield


def run(executor="photo_pipe", **changes):
    return SimpleNamespace(
        **{
            "id": "synthetic-run",
            "capability": "image.generate",
            "executor_type": executor,
            "parameters": {"steps": 8},
            "metadata_json": {},
            "status": "running",
            "started_at": utcnow() - timedelta(seconds=50),
            **changes,
        }
    )


@pytest.mark.parametrize(
    "executor,line,completed,total",
    [
        ("photo_pipe", "4/8 - 9.51s/it\x1b[K", 4, 8),
        ("photo_pipe", " 50%|█████     | 4/8 [00:38<00:38,  9.51s/it]", 4, 8),
        ("wan_video", " 25%|██▌       | 2/8 [00:04<00:12,  0.50it/s]", 2, 8),
        ("echomimic", "2/8 [00:03<00:07, 1.26s/it]", 2, 8),
        ("ace_step_music", "4/8 [00:38<00:38, 9.51s/it]", 4, 8),
        ("chatterbox", "speech.chunk.completed 2/5", 2, 5),
    ],
)
def test_known_numeric_formats(executor, line, completed, total):
    parsed = parse_line(line, run(executor))
    assert parsed["completed"] == completed and parsed["total"] == total
    assert parsed["phase"] == "generating"


def test_weight_loading_and_speech_token_ceiling_do_not_become_completion():
    target = run()
    for line in (
        "118/297 - 756.52MB/s",
        "8/8 - 100MB/s",
        "9/8 - 1s/it",
        "4/20 - 2s/it",
        "4/8 - 0it/s",
        "nan/8 - 1s/it",
        "image.stage: install arbitrary model",
    ):
        assert parse_line(line, target) is None
    assert parse_line("1000/1000 [00:20<00:00, 50it/s]", run("chatterbox")) == {"phase": "generating"}
    assert parse_line("image.stage: completed", run("chatterbox")) is None


def test_split_cr_ansi_deduplication_and_monotonicity(monkeypatch):
    events = []
    monkeypatch.setattr(
        "app.generation_progress.append_event", lambda _db, _rid, _kind, payload: events.append(payload)
    )
    target = run()
    observe(None, target, {"stderr": "\r4/8 - 9.5s/"})
    assert "generation_progress" not in target.metadata_json
    observe(None, target, {"stderr": "it\x1b[K\r4/8 - 9.5s/it\r2/8 - 9.5s/it\n"})
    assert len(events) == 1 and events[0]["completed"] == 4
    observe(None, target, {"stdout": "image.stage: decoding image on GPU\n"})
    observe(None, target, {"stderr": "6/8 - 9.5s/it\n"})
    assert target.metadata_json["generation_progress"]["phase"] == "finishing"
    assert target.status == "running"  # No parser can publish a successful Run.
    observe(None, target, {"stdout": "z" * 100000})
    assert len(target.metadata_json["generation_progress_buffers"]["stdout"]) == 512


def test_end_of_process_flushes_a_final_unterminated_counter(monkeypatch):
    monkeypatch.setattr("app.generation_progress.append_event", lambda *_: None)
    target = run()
    observe(None, target, {"stderr": "8/8 - 2s/it"})
    observe(None, target, {"alive": False, "exit_code": 0})
    assert target.metadata_json["generation_progress"]["phase"] == "finishing"
    assert target.status == "running"


def test_saved_sampling_eta_has_scope_and_hides_a_stall():
    now = utcnow()
    target = run(
        metadata_json={
            "generation_progress": {
                "phase": "generating",
                "completed": 4,
                "total": 8,
                "unit": "sampling steps",
                "seconds_per_unit": 10,
                "observed_at": now.isoformat(),
            }
        }
    )
    view = projection(target, now=now)
    assert view["fraction"]["completed"] == 4
    assert view["estimate"] == {
        "lower_seconds": 28,
        "upper_seconds": 52,
        "basis": "observed sampling speed",
        "scope": "sampling",
    }
    stale = projection(target, now=now + timedelta(minutes=5))
    assert stale["estimate"] is None and stale["fraction"] is None
    target.status = "cancel_requested"
    assert projection(target)["estimate"] is None
    target.status = "succeeded"
    assert projection(target)["phase"] == "succeeded"


def test_composition_and_unknown_progress_remain_indeterminate():
    assert projection(run("media_compose"))["phase"] == "finishing"
    assert projection(run("chatterbox"))["estimate"] is None
    assert projection(run("unsupported")) is None
    values = active_progress([run(status="succeeded"), run(status="queued"), run("wan_video")])
    assert len(values) == 1 and values[0]["status"] == "running"
    assert len(active_progress([run() for _ in range(20)])) == 6
