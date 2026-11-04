"""Fixed owned offline MMAudio rendering, timing verification and complete publication."""

import json
import os
import signal
import sys
import time
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ai_station_runner.effects_contract import RAM_MIB, EffectsRequest, installation_observation, video_path
from ai_station_runner.effects_video import conditioning
from ai_station_runner.memory_scope import current_group, require_scope
from ai_station_runner.security import resolve_child


def models(runtime, weights):
    import torch
    from mmaudio.ext.bigvgan_v2.bigvgan import BigVGAN
    from mmaudio.model.networks import get_my_mmaudio
    from mmaudio.model.utils import features_utils
    from open_clip.factory import load_checkpoint
    from open_clip.model import CLIP

    # Use only verified local files, including upstream constructors which normally
    # resolve mutable Hub names. These substitutions are fixed internal functions.
    def local_clip(name, return_transform=False):
        if name != "hf-hub:apple/DFN5B-CLIP-ViT-H-14-384" or return_transform:
            raise ValueError("Unexpected CLIP constructor")
        cfg = json.loads((weights / "clip/open_clip_config.json").read_text())["model_cfg"]
        model = CLIP(**cfg)
        load_checkpoint(model, str(weights / "clip/open_clip_pytorch_model.bin"), weights_only=True)
        return model.eval()

    features_utils.create_model_from_pretrained = local_clip
    original = BigVGAN.from_pretrained

    def local_vocoder(cls, name, **kwargs):
        if name != "nvidia/bigvgan_v2_44khz_128band_512x":
            raise ValueError("Unexpected vocoder constructor")
        return original(str(weights / "vocoder"), local_files_only=True, **kwargs)

    BigVGAN.from_pretrained = classmethod(local_vocoder)
    net = get_my_mmaudio("large_44k_v2").to("cuda:0", torch.bfloat16).eval()
    net.load_weights(torch.load(weights / "flow.pth", map_location="cpu", weights_only=True))
    features = (
        features_utils.FeaturesUtils(
            tod_vae_ckpt=weights / "vae.pth",
            synchformer_ckpt=weights / "sync.pth",
            enable_conditions=True,
            mode="44k",
            need_vae_encoder=False,
        )
        .to("cuda:0", torch.bfloat16)
        .eval()
    )
    for name, module in list(sys.modules.items()):
        if (
            name.startswith("mmaudio.")
            and getattr(module, "__file__", None)
            and not Path(module.__file__).resolve().is_relative_to(runtime / "mmaudio")
        ):
            raise ValueError("MMAudio imported from another installation")
    if any(p.device != torch.device("cuda:0") for m in (net, features) for p in m.parameters()):
        raise ValueError("Effects weights must remain on the allocated GPU")
    return net, features


def render(request, runtime, weights, source, work):
    from importlib.metadata import version

    required = {
        "torch": "2.8.0+cu126",
        "torchvision": "0.23.0+cu126",
        "torchaudio": "2.8.0+cu126",
        "open_clip_torch": "2.32.0",
        "timm": "1.0.30",
        "av": "16.1.0",
        "numpy": "2.0.2",
    }
    if any(version(k) != v for k, v in required.items()):
        raise ValueError("Effects dependencies differ from the qualified profile")
    import numpy as np
    import soundfile as sf
    import torch
    from mmaudio.eval_utils import generate
    from mmaudio.model.flow_matching import FlowMatching
    from mmaudio.model.sequence_config import CONFIG_44K

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1 or not torch.cuda.is_bf16_supported():
        raise ValueError("Allocate one BF16-capable CUDA GPU")
    torch.cuda.reset_peak_memory_stats()
    print("effects.model.loading", file=sys.__stdout__, flush=True)
    net, features = models(runtime, weights)
    samples = request.video.frames * 44100 // request.video.fps
    complete = np.zeros(samples, dtype=np.float32)
    parts = []
    started = time.monotonic()
    from ai_station_runner.effects_timing import cue_cuts, effects_windows, window_prompt

    windows = effects_windows(
        request.video.frames, request.video.fps, cuts=cue_cuts(request.video.frames, request.cues)
    )
    total = len(windows)
    for index, (window, clip, sync) in enumerate(conditioning(source, request.video, windows=windows)):
        if time.time() >= request.deadline_at:
            raise ValueError("Effects deadline elapsed")
        print(f"effects.window.started {index + 1}/{total}", file=sys.__stdout__, flush=True)
        cfg = CONFIG_44K
        cfg.duration = window.conditioning_frames / request.video.fps
        net.update_seq_lengths(cfg.latent_seq_len, cfg.clip_seq_len, cfg.sync_seq_len)
        rng = torch.Generator(device="cuda")
        rng.manual_seed(request.seed + index)
        with torch.inference_mode():
            raw = (
                generate(
                    clip.unsqueeze(0),
                    sync.unsqueeze(0),
                    [window_prompt(window.first_frame, request.prompt, request.cues)],
                    negative_text=[request.negative_prompt],
                    feature_utils=features,
                    net=net,
                    fm=FlowMatching(min_sigma=0, inference_mode="euler", num_steps=request.steps),
                    rng=rng,
                    cfg_strength=request.cfg,
                    clip_batch_size_multiplier=1,
                    sync_batch_size_multiplier=1,
                )
                .float()
                .cpu()[0]
                .numpy()
            )
        if raw.ndim != 2 or raw.shape[0] != 1 or not np.isfinite(raw).all():
            raise ValueError("Invalid effects PCM")
        count = window.end_sample - window.first_sample
        if raw.shape[-1] < count or raw.shape[-1] > 8 * 44100 + 2048:
            raise ValueError("Effects output does not cover the planned window")
        part = raw[0, :count].copy()
        overlap = window.overlap_samples
        if overlap:
            ramp = np.linspace(0, 1, overlap, dtype=np.float32)
            part[:overlap] = (
                complete[window.first_sample : window.first_sample + overlap] * (1 - ramp)
                + part[:overlap] * ramp
            )
        if request.cues:
            fade = min(220, count // 2)
            if fade and window.first_frame == window.region_first_frame:
                part[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
            if fade and window.first_frame + window.frames == window.region_end_frame:
                part[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        complete[window.first_sample : window.end_sample] = part
        name = f"part-{index:02d}.wav"
        sf.write(work / name, part, 44100, subtype="FLOAT")
        parts.append(
            {
                "first_frame": window.first_frame,
                "region_first_frame": window.region_first_frame,
                "region_end_frame": window.region_end_frame,
                "prompt": window_prompt(window.first_frame, request.prompt, request.cues),
                "frames": window.frames,
                "conditioning_frames": window.conditioning_frames,
                "first_sample": window.first_sample,
                "end_sample": window.end_sample,
                "overlap_samples": overlap,
                "raw_samples": raw.shape[-1],
                "path": name,
            }
        )
        print(f"effects.window.completed {index + 1}/{total}", file=sys.__stdout__, flush=True)
    if not parts or parts[-1]["end_sample"] != samples:
        raise ValueError("Effects timeline is incomplete")
    peak = float(np.abs(complete).max())
    if not np.isfinite(complete).all() or not 1e-6 < peak <= 2:
        raise ValueError("Effects are silent or invalid")
    gain = min(1, 0.99 / peak)
    complete *= gain
    sf.write(work / "complete.wav", complete, 44100, subtype="PCM_16")
    return {
        "verified": True,
        "samples": samples,
        "sample_rate": 44100,
        "channels": 1,
        "duration_seconds": samples / 44100,
        "parts": parts,
        "gain": gain,
        "generation_seconds": time.monotonic() - started,
        "peak_gpu_allocated_mib": int(torch.cuda.max_memory_allocated() / 1024**2),
        "peak_scope_memory_bytes": int((current_group() / "memory.peak").read_text()),
    }


def run(receipt):
    if receipt.resolve() != receipt or receipt.stat().st_size > 65536:
        raise ValueError("Invalid internal effects receipt")
    record = json.loads(receipt.read_text())
    if set(record) != {"request", "runtime", "models", "python"}:
        raise ValueError("Invalid effects configuration")
    request = EffectsRequest.model_validate(record["request"])
    rid = str(request.run_id)
    root = receipt.parents[3]
    if receipt != root / f"runs/{rid}/effects-launch/request.json":
        raise ValueError("Effects receipt ownership changed")
    require_scope(rid, RAM_MIB)
    if time.time() >= request.deadline_at:
        raise ValueError("Effects deadline elapsed")
    runtime, weights = Path(record["runtime"]), Path(record["models"])
    if request.environment_id:
        from ai_station_runner.effects_environment import resolve_id

        selected = resolve_id(root, request.environment_id)
        if (
            Path(sys.base_prefix).resolve() != selected["environment"] / "python"
            or runtime != selected["mmaudio_dir"]
            or weights != selected["mmaudio_models"]
        ):
            raise ValueError("Sound must execute its exact frozen environment")
        signal.setitimer(signal.ITIMER_REAL, min(1800, request.deadline_at - time.time()))
    if installation_observation(runtime, weights) != request.observation:
        raise ValueError("Effects implementation/model changed since queuing")
    source = video_path(root, request.video)
    work = resolve_child(root, f"runs/{rid}/effects")
    relative = f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.wav"
    output = resolve_child(root, relative)
    if work != root / f"runs/{rid}/effects" or work.exists() or output != root / relative or output.exists():
        raise ValueError("Inspect existing effects work")
    work.mkdir(parents=True, mode=0o700)
    with (work / "model.log").open("x") as log, redirect_stdout(log), redirect_stderr(log):
        report = render(request, runtime, weights, source, work)
    video_path(root, request.video)
    expected = request.video.frames * 44100 // request.video.fps
    with wave.open(str(work / "complete.wav")) as wav:
        if (wav.getnframes(), wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (
            expected,
            44100,
            1,
            2,
        ):
            raise ValueError("Final effects WAV timing/format changed")
        if len(wav.readframes(expected)) != expected * 2:
            raise ValueError("Effects output is truncated")
    report.update(
        run_id=rid, observation=request.observation, source_sha256=request.video.sha256, prompt=request.prompt
    )
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False))
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.resolve() != output:
        raise ValueError("Effects output traverses a symlink")
    os.link(work / "complete.wav", output)
    (work / "complete.wav").unlink()
    print("effects.completed", flush=True)


if __name__ == "__main__":
    run(Path(sys.argv[1]))
