"""Actual bounded CPU inference against a tiny synthetic ONNX/tokenizer fixture."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import onnx
import pytest
from app import embedding_models as models
from app.config import get_settings
from app.db import session_factory
from app.models import MemoryEntry
from fastapi.testclient import TestClient
from onnx import TensorProto, helper, numpy_helper
from test_managed_embeddings import drain, prepare
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from tokenizers.processors import TemplateProcessing


@pytest.fixture
def tiny_model(monkeypatch):
    root = get_settings().data_dir
    folder = models.directory(root, create=True)
    vocab = {
        "<unk>": 0,
        "<s>": 1,
        "</s>": 2,
        "query": 3,
        "passage": 4,
        ":": 5,
        "Apple": 6,
        "Pear": 7,
        "common": 8,
    }
    tokenizer = Tokenizer(WordLevel(vocab, unk_token="<unk>"))
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.post_processor = TemplateProcessing(
        single="<s> $A </s>", special_tokens=[("<s>", 1), ("</s>", 2)]
    )
    tokenizer.save(str(folder / "tokenizer.json"))
    weights = np.zeros((len(vocab), 384), dtype=np.float32)
    weights[:, 2] = 0.01
    weights[6, 0], weights[7, 1] = 1.0, 1.0
    graph = helper.make_graph(
        [helper.make_node("Gather", ["weights", "input_ids"], ["last_hidden_state"])],
        "synthetic-embedding",
        [
            helper.make_tensor_value_info(name, TensorProto.INT64, [1, "tokens"])
            for name in ["input_ids", "attention_mask", "token_type_ids"]
        ],
        [helper.make_tensor_value_info("last_hidden_state", TensorProto.FLOAT, [1, "tokens", 384])],
        [numpy_helper.from_array(weights, name="weights")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 10
    onnx.save(model, str(folder / "model_quantized.onnx"))
    specs = {
        name: {
            "remote": name,
            "size": (folder / name).stat().st_size,
            "sha256": hashlib.sha256((folder / name).read_bytes()).hexdigest(),
        }
        for name in models.FILES
    }
    monkeypatch.setattr(models, "FILES", specs)
    models.write_receipt(root)
    return root, specs


def wrapper(tmp_path, specs):
    path = tmp_path / "actual_cpu_fixture.py"
    path.write_text("""import json,sys
from app import embedding_models
embedding_models.FILES=json.loads(sys.argv.pop())
from app.embedding_cpu import main
main()
""")
    return path


def test_actual_cpu_child_chunks_complete_long_text_and_normalizes(tiny_model, tmp_path):
    root, specs = tiny_model
    script = wrapper(tmp_path, specs)
    text = "common " * 1500 + "Pear"
    result = subprocess.run(
        [sys.executable, str(script), str(root), str(os.getpid()), json.dumps(specs)],
        input=json.dumps({"text": text, "kind": "passage"}) + "\n",
        text=True,
        capture_output=True,
        timeout=20,
        env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2"},
    )
    assert result.returncode == 0, result.stderr
    ready, output = [json.loads(line) for line in result.stdout.splitlines()]
    assert ready == {"ready": True, "device": "CPU", "dimension": 384}
    assert output["chunks"] >= 3 and len(output["vector"]) == 384
    assert output["vector"][1] > 0  # Tail beyond 8k characters participates; no silent truncation.
    assert abs(np.linalg.norm(output["vector"]) - 1) < 1e-6


def test_actual_cpu_setup_index_and_search_use_owned_process(tiny_model, monkeypatch, tmp_path):
    from app.api import app

    root, specs = tiny_model
    script = wrapper(tmp_path, specs)
    original = asyncio.create_subprocess_exec

    async def launch(*argv, **kwargs):
        assert argv[1:3] == ("-m", "app.embedding_cpu")
        return await original(
            sys.executable, str(script), str(root), str(os.getpid()), json.dumps(specs), **kwargs
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    with session_factory()() as session:
        session.add_all(
            [
                MemoryEntry(scope="global", content="Apple common"),
                MemoryEntry(scope="global", content="Pear common"),
            ]
        )
        session.commit()
    client = TestClient(app)
    queued = prepare(client)
    assert queued.status_code == 202, queued.text
    drain()
    setup = client.get("/api/memory/embeddings/setup").json()
    assert setup["configured"] and setup["indexed_count"] == 2, setup["prepare_run"].get("error_message")
    queued = client.post("/api/memory/embeddings/search", json={"query": "Pear"}).json()
    drain()
    result = client.get("/api/runs/" + queued["id"]).json()
    assert result["status"] == "succeeded", result["error_message"]
    assert result["metadata"]["results"][0]["content"] == "Pear common"
    assert result["metadata"]["cpu_process_confirmed_gone"]


def test_parent_death_kills_only_its_owned_embedding_child(tmp_path):
    import signal
    import time

    child = tmp_path / "owned_waiting_child.py"
    child.write_text("""import sys,time
from app.embedding_cpu import bind_parent
bind_parent(int(sys.argv[1]))
print("ready",flush=True)
time.sleep(120)
""")
    parent = tmp_path / "owned_parent.py"
    pidfile = tmp_path / "child.pid"
    parent.write_text("""import os,subprocess,sys,time
from pathlib import Path
p=subprocess.Popen([sys.executable,sys.argv[1],str(os.getpid())],stdout=subprocess.PIPE,text=True,start_new_session=True)
assert p.stdout.readline().strip()=="ready"
Path(sys.argv[2]).write_text(str(p.pid))
time.sleep(120)
""")
    supervisor = subprocess.Popen(
        [sys.executable, str(parent), str(child), str(pidfile)], start_new_session=True
    )
    child_pid = None
    child_start = None

    def live(pid):
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()
            return fields[0] != "Z" and (child_start is None or fields[19] == child_start)
        except (FileNotFoundError, ProcessLookupError):
            return False

    try:
        deadline = time.monotonic() + 5
        while not pidfile.exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        child_pid = int(pidfile.read_text())
        child_start = Path(f"/proc/{child_pid}/stat").read_text().split(") ", 1)[1].split()[19]
        assert live(child_pid)
        supervisor.kill()
        supervisor.wait(timeout=3)
        deadline = time.monotonic() + 3
        while live(child_pid):
            assert time.monotonic() < deadline, "Owned embedding process survived its parent"
            time.sleep(0.02)
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=3)
        if child_pid is not None and live(child_pid):
            os.killpg(child_pid, signal.SIGKILL)
