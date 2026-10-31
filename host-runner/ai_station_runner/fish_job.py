"""Owned complete speech rendering; validate the frozen profile before model imports."""

import json
import os
import signal
import sys
import time
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ai_station_runner.fish_contract import (
    CODEC_VRAM_MIB,
    DIRECTIONS,
    PRIMARY_VRAM_MIB,
    RAM_MIB,
    FishRequest,
    installation_observation,
    reference_bytes,
)
from ai_station_runner.memory_scope import require_scope
from ai_station_runner.security import resolve_child
from ai_station_runner.speech_chunks import text_chunks


class GpuMemoryUnavailable(ValueError):
    """Another workload took VRAM after initial resource admission."""


def verify_module_locations(runtime, modules):
    # Fish uses namespace packages, whose __file__ is legitimately None.
    # Check imported implementation files, including editable installations.
    for name, module in list(modules.items()):
        if name.startswith("fish_speech.") and getattr(module, "__file__", None):
            if not Path(module.__file__).resolve().is_relative_to(runtime / "fish_speech"):
                raise ValueError("Fish was imported from another installation")


def require_gpu_memory(torch, device, minimum_mib):
    free, _ = torch.cuda.mem_get_info(device)
    if type(free) is not int or free < minimum_mib * 1024**2:
        raise GpuMemoryUnavailable(
            "GPU memory became unavailable while loading expressive speech. "
            "Wait for other GPU workloads to finish, then retry this task."
        )


def render(request, *, runtime, models, work, reference):
    """Only the checked entry calls this; model imports remain inside the owned child."""
    import numpy as np
    import soundfile as sf
    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != 2:
        raise ValueError("The allocated Fish GPU pair is unavailable")
    for device in (0, 1):
        with torch.cuda.device(device):
            if not torch.cuda.is_bf16_supported():
                raise ValueError("This Fish profile requires BF16-capable CUDA GPUs")
            torch.cuda.reset_peak_memory_stats(device)
    from fish_speech.models.text2semantic.inference import (
        decode_one_token_ar,
        decode_to_audio,
        encode_audio,
        generate_long,
        load_codec_model,
    )
    from fish_speech.models.text2semantic.llama import DualARTransformer
    from fish_speech.tokenizer import IM_END_TOKEN

    verify_module_locations(runtime, sys.modules)

    started = time.monotonic()
    print("speech.model.loading", file=sys.__stdout__, flush=True)
    model = DualARTransformer.from_pretrained(models, load_weights=True, max_length=4096)
    # CPU loading may take a minute. An external runtime can claim VRAM after
    # native admission, so recheck before copying any semantic weights to CUDA.
    require_gpu_memory(torch, 0, PRIMARY_VRAM_MIB)
    require_gpu_memory(torch, 1, CODEC_VRAM_MIB)
    model = model.to(device="cuda:0", dtype=torch.bfloat16).eval()
    with torch.device("cuda:0"):
        model.setup_caches(max_batch_size=1, max_seq_len=4096, dtype=torch.bfloat16)
    model._cache_setup_done = True
    require_gpu_memory(torch, 1, CODEC_VRAM_MIB)
    codec = load_codec_model(models / "codec.pth", "cuda:1", torch.bfloat16)
    verify_module_locations(runtime, sys.modules)
    if any(p.device != torch.device("cuda:0") for p in model.parameters()) or any(
        p.device != torch.device("cuda:1") for p in codec.parameters()
    ):
        raise ValueError("Fish model weights must stay on the allocated GPUs")
    reference_tokens = encode_audio(str(reference), codec, "cuda:1").cpu()
    end_id = model.tokenizer.get_token_id(IM_END_TOKEN)
    parts = []
    prefix = " ".join(
        filter(
            None,
            (
                DIRECTIONS[request.direction],
                {"natural": "", "slow": "[slowly]", "fast": "[fast]"}[request.pace],
            ),
        )
    )
    chunks = text_chunks(request.text)
    for index, chunk in enumerate(chunks):
        if time.time() >= request.deadline_at:
            raise ValueError("Speech execution deadline elapsed")
        print(f"speech.chunk.started {index + 1}/{len(chunks)}", file=sys.__stdout__, flush=True)
        ended = False

        def checked_decode(*args, **kwargs):
            nonlocal ended
            token = decode_one_token_ar(*args, **kwargs)
            ended = ended or int(token.reshape(model.config.num_codebooks + 1, -1)[0, -1]) == end_id
            return token

        codes = []
        torch.manual_seed(42 + index)
        with torch.inference_mode():
            for response in generate_long(
                model=model,
                device="cuda:0",
                decode_one_token=checked_decode,
                text=(prefix + " " + chunk).strip(),
                max_new_tokens=1024,
                top_p=0.7,
                top_k=30,
                temperature=0.7,
                compile=False,
                prompt_text=[request.reference_text],
                prompt_tokens=[reference_tokens],
                chunk_length=1000,
            ):
                if response.action == "sample":
                    if not ended:
                        raise ValueError("Speech stopped without EOS; partial audio will not be published")
                    codes.append(response.codes)
                    ended = False
            if not codes:
                raise ValueError("The speech model returned no complete audio")
            audio = decode_to_audio(torch.cat(codes, dim=1).to("cuda:1"), codec).float().cpu().numpy()
        if not np.isfinite(audio).all() or not 0.1 <= len(audio) / codec.sample_rate <= 90:
            raise ValueError("Speech returned invalid or unbounded PCM")
        if not 1e-6 < float(np.max(np.abs(audio))) <= 2:
            raise ValueError("Speech output is silent or invalid")
        path = work / f"part-{index:02d}.wav"
        if path.exists() or path.is_symlink():
            raise ValueError("Inspect existing speech parts")
        sf.write(path, audio, codec.sample_rate, subtype="PCM_16")
        parts.append({"path": path.name, "text": chunk, "samples": len(audio), "eos": True})
        print(f"speech.chunk.completed {index + 1}/{len(chunks)}", file=sys.__stdout__, flush=True)
    return {
        "parts": parts,
        "sample_rate": codec.sample_rate,
        "seconds": time.monotonic() - started,
        "peak_allocated_mib": [int(torch.cuda.max_memory_allocated(i) / 1024**2) for i in (0, 1)],
    }


def combine(work, report, output):
    temporary = work / "complete.wav"
    total = 0
    with temporary.open("xb") as raw, wave.open(raw, "wb") as complete:
        complete.setnchannels(1)
        complete.setsampwidth(2)
        complete.setframerate(report["sample_rate"])
        for part in report["parts"]:
            path = resolve_child(work, part["path"])
            if path != work / part["path"] or path.stat().st_size > 20 * 1024**2:
                raise ValueError("Speech stem changed")
            with wave.open(str(path), "rb") as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (
                    1,
                    2,
                    report["sample_rate"],
                ):
                    raise ValueError("Speech stems have incompatible formats")
                count = wav.getnframes()
                samples = wav.readframes(count)
                if count != part["samples"] or len(samples) != count * 2 or not part["eos"]:
                    raise ValueError("Speech stem is incomplete")
                total += count
                if total / report["sample_rate"] > 300 or total * 2 + 44 > 20 * 1024**2:
                    raise ValueError("Complete speech exceeds its output budget")
                complete.writeframes(samples)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.resolve() != output:
        raise ValueError("Speech output must not traverse symlinks")
    os.link(temporary, output)  # Never replace an existing result.
    temporary.unlink()
    return total


def run(receipt):
    if receipt.resolve() != receipt or receipt.stat().st_size > 65536:
        raise ValueError("Invalid internal speech receipt")
    record = json.loads(receipt.read_text())
    if set(record) != {"request", "runtime", "models", "python"}:
        raise ValueError("Invalid internal speech configuration")
    request = FishRequest.model_validate(record["request"])
    root = receipt.parents[3]
    run_id = str(request.run_id)
    if receipt != root / f"runs/{run_id}/fish-launch/request.json":
        raise ValueError("Speech launch ownership changed")
    require_scope(run_id, RAM_MIB)
    if time.time() >= request.deadline_at:
        raise ValueError("Speech execution deadline elapsed")
    runtime, models = Path(record["runtime"]), Path(record["models"])
    if request.environment_id:
        from ai_station_runner.fish_environment import resolve_id

        chosen = resolve_id(root, request.environment_id)
        if (
            Path(sys.base_prefix).resolve() != chosen["environment"] / "fish/python"
            or runtime != chosen["fish_speech_dir"]
            or models != chosen["fish_speech_models"]
            or Path(record["python"]) != chosen["fish_speech_python"]
        ):
            raise ValueError("Fish must execute its exact frozen environment")
        signal.setitimer(signal.ITIMER_REAL, min(1800, request.deadline_at - time.time()))

        def offline(event, args):
            if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
                raise PermissionError("Managed Fish speech stays offline")

        sys.addaudithook(offline)
    if installation_observation(runtime, models) != request.observation:
        raise ValueError("Fish implementation or model changed since queuing")
    data = reference_bytes(root, request.reference.model_dump())
    output_relative = f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.wav"
    output = resolve_child(root, output_relative)
    work = resolve_child(root, f"runs/{run_id}/fish-speech")
    if (
        output != root / output_relative
        or work != root / f"runs/{run_id}/fish-speech"
        or output.exists()
        or work.exists()
    ):
        raise ValueError("Inspect existing speech work instead of overwriting it")
    work.mkdir(mode=0o700, parents=True)
    reference = work / "reference.wav"
    reference.write_bytes(data)
    # Upstream diagnostic prompt dumps cannot impersonate measured wrapper events.
    with (work / "model.log").open("x") as log, redirect_stdout(log), redirect_stderr(log):
        report = render(request, runtime=runtime, models=models, work=work, reference=reference)
    report.update(
        run_id=run_id,
        observation=request.observation,
        text=request.text,
        direction=request.direction,
        pace=request.pace,
        reference_sha256=request.reference.sha256,
    )
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False))
    samples = combine(work, report, output)
    print(f"speech.completed parts={len(report['parts'])} samples={samples}", flush=True)


if __name__ == "__main__":
    try:
        run(Path(sys.argv[1]))
    except GpuMemoryUnavailable as exc:
        print(str(exc), file=sys.stderr, flush=True)
        sys.exit(2)
