"""Fixed offline CPU inference child, owned by exactly one worker Run."""

import ctypes
import json
import os
import resource
import signal
import sys
from pathlib import Path

from app.embedding_models import CPU_THREADS, DIMENSION, FILES, MAX_CHARACTERS, model_file, verify_file


def bind_parent(expected_pid):
    # Installed before heavyweight imports; also close the parent-death race.
    if os.getppid() != expected_pid or ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL) != 0:
        raise RuntimeError("Cannot establish embedding process ownership")
    if os.getppid() != expected_pid:
        raise RuntimeError("The embedding worker disappeared during startup")
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024**2, 1024**2))


class Encoder:
    def __init__(self, root):
        for name in FILES:
            verify_file(root, name)
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = CPU_THREADS
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(
            str(model_file(root, "model_quantized.onnx")), options, providers=["CPUExecutionProvider"]
        )
        self.tokenizer = Tokenizer.from_file(str(model_file(root, "tokenizer.json")))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()

    def segments(self, text, kind):
        prefix = "query: " if kind == "query" else "passage: "
        offsets = self.tokenizer.encode(text, add_special_tokens=False).offsets
        if not offsets:
            raise ValueError("Embedding text has no usable tokens")
        start = 0
        for index in range(0, len(offsets), 384):
            end = offsets[min(index + 384, len(offsets)) - 1][1]
            if index + 384 >= len(offsets):
                end = len(text)
            if end <= start:
                continue
            pending = [(start, end)]
            while pending:
                lo, hi = pending.pop(0)
                encoded = self.tokenizer.encode(prefix + text[lo:hi])
                if len(encoded.ids) > 512:
                    if hi - lo <= 1:
                        raise ValueError("Embedding token bound cannot be satisfied")
                    middle = (lo + hi) // 2
                    pending[0:0] = [(lo, middle), (middle, hi)]
                    continue
                yield encoded, hi - lo
            start = end

    def encode(self, text, kind):
        import numpy as np

        if (
            kind not in {"query", "passage"}
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > MAX_CHARACTERS
        ):
            raise ValueError("Invalid bounded embedding input")
        pooled, weight, chunks = np.zeros(DIMENSION, dtype=np.float64), 0, 0
        names = {item.name for item in self.session.get_inputs()}
        for encoded, length in self.segments(text, kind):
            inputs = {
                "input_ids": np.array([encoded.ids], dtype=np.int64),
                "attention_mask": np.array([encoded.attention_mask], dtype=np.int64),
                "token_type_ids": np.array([encoded.type_ids], dtype=np.int64),
            }
            output = self.session.run(None, {name: inputs[name] for name in names})[0]
            if output.shape != (1, len(encoded.ids), DIMENSION) or not np.isfinite(output).all():
                raise ValueError("Embedding engine returned invalid hidden states")
            mask = np.array(encoded.attention_mask, dtype=np.float64)
            vector = (output[0] * mask[:, None]).sum(axis=0) / mask.sum()
            norm = np.linalg.norm(vector)
            if not np.isfinite(norm) or norm <= 0:
                raise ValueError("Embedding engine returned an empty vector")
            pooled += vector / norm * length
            weight += length
            chunks += 1
            if chunks > 256:
                raise ValueError("Embedding chunk bound exceeded")
        norm = np.linalg.norm(pooled)
        if weight <= 0 or not np.isfinite(norm) or norm <= 0:
            raise ValueError("Embedding engine returned an empty result")
        return {"vector": (pooled / norm).tolist(), "chunks": chunks}


def main():
    bind_parent(int(sys.argv[2]))
    encoder = Encoder(Path(sys.argv[1]))
    print(json.dumps({"ready": True, "device": "CPU", "dimension": DIMENSION}), flush=True)
    while line := sys.stdin.readline(160001):
        if len(line) > 160000:
            raise ValueError("Embedding request exceeded its bound")
        body = json.loads(line)
        if not isinstance(body, dict) or set(body) != {"text", "kind"}:
            raise ValueError("Invalid embedding request")
        print(json.dumps(encoder.encode(body["text"], body["kind"])), flush=True)


if __name__ == "__main__":
    main()
