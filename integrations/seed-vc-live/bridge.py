# SPDX-License-Identifier: GPL-3.0-only
"""Independent offline Seed-VC streaming worker; no imports from the core app."""

import argparse
import contextlib
import ctypes
import hashlib
import hmac
import io
import json
import os
import re
import signal
import stat
import struct
import sys
import threading
import time
import types
from pathlib import Path

RATE = 22050
SAMPLES = 4410
BYTES = SAMPLES * 4
PREFIX = struct.Struct("!I")
CLOCK = struct.Struct("!IQ")


class NoHostAudio(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise RuntimeError("Live browser conversion cannot open host audio devices")


def read_request(path):
    path = Path(path)
    if path.resolve() != path:
        raise ValueError("Voice requests cannot use symlinks")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
            or info.st_size > 8192
        ):
            raise ValueError("Voice request must be a bounded private owned file")
        body = json.loads(source.read(8193))
    if not isinstance(body, dict) or set(body) != {
        "runtime_root",
        "reference_fd",
        "reference_sha256",
        "seed",
        "parent_pid",
    }:
        raise ValueError("Unknown voice conversion request fields")
    if type(body["seed"]) is not int or not 0 <= body["seed"] < 2**31:
        raise ValueError("Voice seed is outside the session profile")
    if type(body["parent_pid"]) is not int or body["parent_pid"] <= 1:
        raise ValueError("Voice worker needs its owned parent identity")
    import fcntl

    if (
        not isinstance(body["runtime_root"], str)
        or not isinstance(body["reference_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", body["reference_sha256"])
        or type(body["reference_fd"]) is not int
        or body["reference_fd"] < 3
    ):
        raise ValueError("Voice runtime and reference coordinates are invalid")
    runtime = Path(body["runtime_root"])
    if runtime.resolve() != runtime or not runtime.is_dir():
        raise ValueError("Voice input must use its fixed runtime")
    fd = body["reference_fd"]
    # Stable Linux UAPI values; some standalone CPython builds omit the names.
    seals = 0x0F
    info = os.fstat(fd)
    if (
        os.readlink(f"/proc/self/fd/{fd}") != "/memfd:ai-station-live-reference (deleted)"
        or fcntl.fcntl(fd, getattr(fcntl, "F_GET_SEALS", 1034)) & seals != seals
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 0
        or info.st_size > 20 * 1024**2
    ):
        raise ValueError("Voice reference must be an immutable private memory snapshot")
    with os.fdopen(os.dup(fd), "rb") as source:
        source.seek(0)
        data = source.read(20 * 1024**2 + 1)
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), body["reference_sha256"]):
        raise ValueError("Voice reference snapshot changed")
    return body, data


def bind_parent(expected):
    if sys.platform != "linux" or os.getppid() != expected:
        raise ValueError("The qualified voice worker needs its live native parent")
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Cannot bind voice lifetime to its parent")
    if os.getppid() != expected:
        raise InterruptedError("Live native parent exited during voice startup")


class StreamVoice:
    def __init__(self, runtime, reference_bytes, seed):
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", MODELSCOPE_OFFLINE="1")
        sys.modules["sounddevice"] = NoHostAudio("sounddevice")
        source = runtime / "sdk"
        models = runtime / "models"
        sys.path.insert(0, str(source))
        import librosa
        import numpy as np
        import realtime_vc_engine as sdk
        import soundfile as sf
        import torch
        import yaml
        from funasr import AutoModel

        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise RuntimeError("The voice process requires exactly its allocated visible GPU")
        torch.cuda.set_device(0)
        torch.set_num_threads(2)
        self.torch, self.np, self.seed = torch, np, seed

        def model_object(repository, filename="pytorch_model.bin", config_filename=None):
            objects = {
                ("funasr/campplus", "campplus_cn_common.bin"): models / "campplus_cn_common.bin",
                ("FunAudioLLM/CosyVoice-300M", "hift.pt"): models / "hift.pt",
            }
            if config_filename is not None or (repository, filename) not in objects:
                raise ValueError("Unqualified external voice model resolution")
            return str(objects[(repository, filename)])

        sdk.load_custom_model_from_hf = model_object
        config = yaml.safe_load((models / "config_dit_mel_seed_uvit_xlsr_tiny.yml").read_text())
        config["model_params"]["speech_tokenizer"]["name"] = str(models / "xlsr")
        config_fd = self.memory_file("ai-station-live-voice-config", yaml.safe_dump(config).encode())
        config_path = Path(f"/proc/self/fd/{config_fd}")
        for name in ("DiT_uvit_tat_xlsr_ema.pth", "campplus_cn_common.bin", "hift.pt"):
            tensors = torch.load(models / name, map_location="cpu", weights_only=True)
            del tensors
        engine = sdk.RealtimeVCEngine.__new__(sdk.RealtimeVCEngine)
        engine.device = torch.device("cuda:0")
        engine.fp16 = True
        engine.config = sdk.RealtimeVCConfig()
        args = types.SimpleNamespace(
            gpu=0,
            fp16=True,
            checkpoint_path=str(models / "DiT_uvit_tat_xlsr_ema.pth"),
            config_path=str(config_path),
        )
        try:
            engine.model_set = engine._load_models(args)
        finally:
            os.close(config_fd)
        engine.vad_model = AutoModel(
            model=str(models / "vad"),
            disable_pbar=True,
            log_level="ERROR",
            disable_update=True,
            trust_remote_code=False,
        )
        engine.prompt_condition, engine.mel2, engine.style2 = None, None, None
        engine.reference_wav_name, engine.prompt_len, engine.ce_dit_difference = "", 3, 2.0
        engine._in_ready = threading.Event()
        engine.last_error_print_time = 0
        engine.get_device_channels = lambda: 1
        settings = {
            "block_time": 0.2,
            "crossfade_time": 0.04,
            "extra_time_ce": 2.5,
            "extra_time": 0.5,
            "extra_time_right": 0.04,
            "diffusion_steps": 6,
            "inference_cfg_rate": 0.7,
            "max_prompt_length": 3,
        }
        for key, value in settings.items():
            setattr(engine.config, key, value)
        reference, _ = librosa.load(io.BytesIO(reference_bytes), sr=RATE, duration=30)
        if len(reference) < RATE or not np.isfinite(reference).all() or np.max(np.abs(reference)) < 1e-4:
            raise ValueError("Choose a clear reference recording with at least one second of speech")
        conditioned = io.BytesIO()
        sf.write(conditioned, reference, RATE, format="WAV")
        self._reference_fd = self.memory_file("ai-station-live-voice-conditioning", conditioned.getvalue())
        engine.config.reference_audio_path = f"/proc/self/fd/{self._reference_fd}"
        engine._prepare_buffers()
        original = engine._custom_infer
        self._failure = None

        def infer(*args):
            try:
                return original(*args)
            except Exception:
                self._failure = "Local voice inference failed"
                raise

        # The external engine catches inference exceptions and emits silence.
        # Keep silence on the wire but make that error fatal to this session.
        engine._custom_infer = infer
        self.engine = engine
        for _ in range(3):
            self.convert(np.zeros(SAMPLES, dtype=np.float32).tobytes())

    @staticmethod
    def memory_file(name, data):
        import fcntl

        fd = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        try:
            with os.fdopen(os.dup(fd), "wb") as target:
                target.write(data)
            os.lseek(fd, 0, os.SEEK_SET)
            fcntl.fcntl(
                fd,
                getattr(fcntl, "F_ADD_SEALS", 1033),
                0x0F,
            )
        except BaseException:
            os.close(fd)
            raise
        return fd

    def convert(self, payload):
        if len(payload) != BYTES:
            raise ValueError("Voice input must contain exactly one PCM block")
        samples = self.np.frombuffer(payload, dtype="<f4")
        if not self.np.isfinite(samples).all() or self.np.max(self.np.abs(samples)) > 1:
            raise ValueError("Voice input contains invalid samples")
        self.torch.manual_seed(self.seed)
        result = self.engine._process_block(samples.copy())
        if self._failure is not None:
            raise RuntimeError(self._failure)
        if result.shape != (SAMPLES,) or not self.np.isfinite(result).all():
            raise RuntimeError("Local voice inference returned invalid audio")
        return self.np.clip(result, -1, 1).astype("<f4").tobytes()


def write_packet(body):
    sys.stdout.buffer.write(PREFIX.pack(len(body)) + body)
    sys.stdout.buffer.flush()


def read_exact(length):
    data = bytearray()
    while len(data) < length:
        chunk = sys.stdin.buffer.read(length - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return bytes(data)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    body, reference = read_request(args.request)
    bind_parent(body["parent_pid"])
    with contextlib.redirect_stdout(sys.stderr):
        engine = StreamVoice(Path(body["runtime_root"]), reference, body["seed"])
    write_packet(b"J" + json.dumps({"ready": True, "sample_rate": RATE, "block_samples": SAMPLES}).encode())
    previous = None
    while True:
        try:
            length = PREFIX.unpack(read_exact(PREFIX.size))[0]
        except EOFError:
            return
        if length != CLOCK.size + BYTES:
            raise ValueError("Voice packet size is invalid")
        packet = read_exact(length)
        sequence, timestamp = CLOCK.unpack_from(packet)
        if timestamp > 4 * 3600 * 1_000_000 or (
            previous is not None and (sequence, timestamp) != (previous[0] + 1, previous[1] + 200_000)
        ):
            raise ValueError("Voice packet clock is discontinuous")
        started = time.monotonic()
        with contextlib.redirect_stdout(sys.stderr):
            converted = engine.convert(packet[CLOCK.size :])
        previous = sequence, timestamp
        write_packet(b"A" + packet[: CLOCK.size] + converted)
        write_packet(b"J" + json.dumps({"inference_ms": (time.monotonic() - started) * 1000}).encode())


if __name__ == "__main__":
    main()
