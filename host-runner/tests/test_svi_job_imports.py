"""The offline child must not inherit the Runner's API or inference dependencies on import."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("admitted", [False, True])
def test_offline_svi_child_imports_without_api_server_torch_or_network(tmp_path, admitted):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import builtins,sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.split('.')[0] in {'fastapi','uvicorn','torch'} or name=='ai_station_runner.runtime_install':
        raise AssertionError('Offline child imported an API or eager inference dependency: '+name)
    return original(name,*args,**kwargs)
builtins.__import__=guarded
def offline(event,args):
    if event in {'socket.connect','socket.getaddrinfo','socket.sendto'}:
        raise AssertionError('Offline child attempted network access')
sys.addaudithook(offline)
from ai_station_runner import svi_environment
svi_environment.QUALIFIED=sys.argv[1]=='1'
from ai_station_runner import svi_video_job
assert callable(svi_video_job.main)
print('offline child imports passed')
""",
            "1" if admitted else "0",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "offline child imports passed" in result.stdout
    assert list(tmp_path.iterdir()) == []
