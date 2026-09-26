import subprocess
import sys


def test_wrapper_drains_only_children_in_its_owned_group():
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    try:
        code = """
import subprocess,sys
from ai_station_runner.owned_children import stop_owned_children
child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("ready",flush=True); time.sleep(30)'],stdout=subprocess.PIPE,text=True)
assert child.stdout.readline().strip() == 'ready'
stop_owned_children(grace_seconds=0.05)
assert child.wait(timeout=2) == -9
"""
        result = subprocess.run(
            [sys.executable, "-c", code], start_new_session=True, capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, result.stderr
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_cursor_collection_drains_helpers_on_success_failure_and_invalid_output(tmp_path):
    # Run the real collector in an owned group. Its fake CLI exits while a child
    # retains both output pipes; collection must finish without a five-minute wait.
    for outcome in ("success", "failure", "invalid"):
        cli = tmp_path / f"{outcome}.py"
        cli.write_text(
            "import subprocess,sys,json\n"
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
            + (
                "print(json.dumps({'type':'result','subtype':'success','is_error':False,'result':'proposal'}),flush=True)\n"
                if outcome == "success"
                else "raise SystemExit(3)\n"
                if outcome == "failure"
                else "print('invalid json',flush=True)\n"
            )
        )
        wrapper = """
import os,sys
from ai_station_runner.cursor_job import collect_proposal
try:
    text,metadata=collect_proposal([sys.executable,sys.argv[1]],dict(os.environ),sys.argv[2])
except (ValueError,RuntimeError):
    assert sys.argv[3] != 'success'
else:
    assert sys.argv[3] == 'success' and text == 'proposal'
"""
        result = subprocess.run(
            [sys.executable, "-c", wrapper, str(cli), str(tmp_path), outcome],
            start_new_session=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
