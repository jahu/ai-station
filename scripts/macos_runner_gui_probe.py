"""Real installed Runner under the stock AppKit parent; no Docker or AI model."""

import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHILD = r"""
import json, os, re, subprocess, sys, time
from pathlib import Path
import httpx
from ai_station_runner.source_identity import SOURCE_FINGERPRINT
state = Path(__STATE__)
data = state / 'data'
data.mkdir(mode=0o700)
socket = state / 'runner.sock'
environment = {k:v for k,v in os.environ.items() if k in {'HOME','PATH','LANG','TMPDIR','__CF_USER_TEXT_ENCODING'}}
environment.update(AI_STATION_DATA_HOST_PATH=str(data), AI_STATION_RUNNER_SOCKET=str(socket))
proof = {'component_only':True, 'consumer_gui_qualified':False, 'model_used':False, 'Docker_used':False}
started = time.monotonic()
with (state/'runner.imports.private.log').open('wb') as log:
 child = subprocess.Popen([sys.executable,'-IB','-X','importtime','-m','ai_station_runner.main'],
     env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
 try:
  with httpx.Client(transport=httpx.HTTPTransport(uds=str(socket)), base_url='http://runner', timeout=1, trust_env=False) as client:
   while time.monotonic()-started<20:
    if child.poll() is not None: break
    try:
     response=client.get('/health')
     if response.status_code==200:
      result=response.json()
      if result.get('data_dir')!=str(data) or result.get('source_fingerprint')!=SOURCE_FINGERPRINT:
       raise ValueError('The installed Runner identity changed')
      proof['passed']=True
      break
    except httpx.TransportError: pass
    time.sleep(.05)
  proof.update(elapsed_ms=round((time.monotonic()-started)*1000), return_code_before_cleanup=child.poll())
 finally:
  if child.poll() is None: child.terminate()
  try: child.wait(timeout=15)
  except subprocess.TimeoutExpired:
   child.kill();child.wait(timeout=5);proof['forced_owned_cleanup']=True
text=(state/'runner.imports.private.log').read_text(errors='replace')[-512000:]
imports=[]
for own,total,name in re.findall(r'^import time:\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([A-Za-z][A-Za-z0-9_.]*)\s*$',text,re.M):
 imports.append({'module':name,'self_us':int(own),'cumulative_us':int(total)})
proof['slowest_imports']=sorted(imports,key=lambda r:r['cumulative_us'],reverse=True)[:20]
proof['error_types']=re.findall(r'^([A-Za-z][A-Za-z0-9_]*(?:Error|Exception)):',text,re.M)[-4:]
proof['passed']=proof.get('passed',False)
(state/'result.private.json').write_text(json.dumps(proof))
"""


def main():
    if (
        platform.system() != "Darwin"
        or platform.machine() not in {"arm64", "x86_64"}
        or os.geteuid() == 0
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != "jahu/ai-station"
        or os.environ.get("GITHUB_ACTOR") != "jahu"
        or not sys.flags.isolated
        or not sys.dont_write_bytecode
    ):
        raise ValueError("Use the explicit native public Mac qualification with its installed interpreter")
    os.umask(0o077)
    repo = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo / "scripts"))
    from build_macos_package import native_interface
    from macos_application_probe import inventory, stop_child, verify_layer

    layer = Path(sys.executable).resolve().parent.parent
    architecture = platform.machine()
    _, before = verify_layer(layer, architecture, repo)
    binary, _ = native_interface(repo / ".native-mac/native-interface", architecture)
    with tempfile.TemporaryDirectory(prefix="asrg-", dir="/private/tmp") as temporary:
        state = Path(temporary)
        application = state / "AI Station.app"
        contents = application / "Contents"
        resources = contents / "Resources"
        (contents / "MacOS").mkdir(parents=True)
        (resources / "scripts").mkdir(parents=True)
        executable = contents / "MacOS/AI Station"
        shutil.copy2(binary, executable)
        (resources / "python").symlink_to(layer, target_is_directory=True)
        (contents / "Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "CFBundleExecutable": "AI Station",
                    "CFBundleIdentifier": "io.ai-station.runner-startup-fixture",
                    "CFBundleName": "AI Station Runner Fixture",
                    "CFBundlePackageType": "APPL",
                }
            )
        )
        inner = resources / "scripts/runner-fixture.py"
        inner.write_text(CHILD.replace("__STATE__", repr(str(state))))
        (resources / "scripts/desktop.py").write_text(
            "import subprocess,sys\n"
            "from pathlib import Path\n"
            'subprocess.run([sys.executable,"-IB",str(Path(__file__).with_name("runner-fixture.py"))],check=True,start_new_session=True)\n'
        )
        subprocess.run(
            ["/usr/bin/codesign", "--force", "--sign", "-", str(application)], check=True, timeout=30
        )
        environment = {
            k: v
            for k, v in os.environ.items()
            if k in {"HOME", "PATH", "LANG", "TMPDIR", "__CF_USER_TEXT_ENCODING"}
        }
        with (state / "launcher.private.log").open("wb") as log:
            process = subprocess.Popen(
                [str(executable)], env=environment, stdout=log, stderr=subprocess.STDOUT
            )
            try:
                deadline = time.monotonic() + 120
                result = state / "result.private.json"
                while not result.exists() and time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("The stock native parent exited before its component result")
                    time.sleep(0.1)
                if not result.exists():
                    log.flush()
                    text = (state / "launcher.private.log").read_text(errors="replace")[-65536:]
                    print(
                        json.dumps(
                            {
                                "component_only": True,
                                "passed": False,
                                "error_types": re.findall(
                                    r"^([A-Za-z][A-Za-z0-9_]*(?:Error|Exception)):", text, re.M
                                )[-4:],
                            }
                        ),
                        flush=True,
                    )
                    raise TimeoutError("The stock native parent did not complete its bounded Runner probe")
                proof = json.loads(result.read_text())
                proof["installed_layer_unchanged"] = inventory(layer) == before
                print(json.dumps(proof), flush=True)
                if not proof["passed"] or not proof["installed_layer_unchanged"]:
                    raise RuntimeError(
                        "The installed Runner did not become healthy under its native GUI parent"
                    )
                process.wait(timeout=15)
                if process.returncode:
                    raise RuntimeError("The stock native parent did not exit cleanly")
            finally:
                stop_child(process)


if __name__ == "__main__":
    main()
