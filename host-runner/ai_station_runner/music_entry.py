"""One offline music process. Optional ACE dependencies are imported only here."""

import os
import signal
import sys
import wave
from pathlib import Path
from uuid import UUID

from ai_station_runner.music_protocol import checkpoint_view, no_symlink, wav_metadata
from ai_station_runner.security import resolve_child


def deny_network(event, args):
    if event in {"socket.connect", "socket.sendto", "socket.getaddrinfo"}:
        raise PermissionError("Local music inference cannot access the network")


def generate(body, model_root, checkpoint_root, source_root, work_root):
    # No upstream import runs until checkpoint/source hashes have passed and
    # model code has been copied into a private view, never the approved model.
    view = checkpoint_view(model_root, source_root, checkpoint_root)
    os.environ["ACESTEP_CHECKPOINTS_DIR"] = str(view)
    sys.addaudithook(deny_network)
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.model_downloader import _check_code_mismatch

    class OfflineHandler(AceStepHandler):
        def _get_project_root(self):
            return str(work_root)

        def _ensure_models_present(self, *, checkpoint_path, config_path, **kwargs):
            if Path(checkpoint_path) != view or config_path != "acestep-v15-turbo":
                raise ValueError("Unexpected music checkpoint selection")
            return None

        @staticmethod
        def _sync_model_code_if_needed(config_path, checkpoint_path):
            if config_path != "acestep-v15-turbo" or _check_code_mismatch(config_path, checkpoint_path):
                raise ValueError("Pinned music model code changed; automatic synchronization is forbidden")

    handler = OfflineHandler()
    print("Loading approved local music preset (no additional music LLM).", flush=True)
    status, ready = handler.initialize_service(
        project_root=str(work_root),
        config_path="acestep-v15-turbo",
        device="cuda",
        use_flash_attention=False,
        compile_model=False,
        offload_to_cpu=True,
        offload_dit_to_cpu=True,
        quantization=None,
        use_mlx_dit=False,
        vae_checkpoint="official",
    )
    if not ready:
        raise RuntimeError(f"Local music model initialization failed: {str(status)[:500]}")
    params = GenerationParams(
        task_type="text2music",
        caption=body["caption"],
        lyrics="[Instrumental]" if body["instrumental"] else body["lyrics"],
        instrumental=body["instrumental"],
        duration=float(body["duration_seconds"]),
        seed=body["seed"],
        inference_steps=8,
        thinking=False,
        use_cot_metas=False,
        use_cot_caption=False,
        use_cot_lyrics=False,
        use_cot_language=False,
    )
    config = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[body["seed"]], audio_format="wav")
    print(f"Generating {body['duration_seconds']} seconds of music locally.", flush=True)
    result = generate_music(handler, None, params, config, save_dir=None)
    if not result.success or len(result.audios) != 1:
        raise RuntimeError("Local music generation failed or returned an unexpected number of samples")
    audio = result.audios[0]
    if audio.get("sample_rate") != 48000 or audio.get("params", {}).get("seed") != body["seed"]:
        raise ValueError("Music runtime returned a different sample rate or seed")
    return audio["tensor"]


def write_pcm(tensor, output):
    import torch

    if tensor is None or tensor.ndim != 2 or tensor.shape[0] not in {1, 2}:
        raise ValueError("Music runtime returned an invalid audio tensor")
    if not 48000 * 10 <= tensor.shape[1] <= 48000 * 601:
        raise ValueError("Music runtime returned an invalid number of samples")
    with Path(output).open("xb") as handle, wave.open(handle, "wb") as audio:
        audio.setnchannels(tensor.shape[0])
        audio.setsampwidth(2)
        audio.setframerate(48000)
        for start in range(0, tensor.shape[1], 48000):
            samples = tensor[:, start : start + 48000].detach().cpu()
            if not bool(torch.isfinite(samples).all()):
                raise ValueError("Music output contains non-finite samples")
            samples = (samples.clamp(-1, 1) * 32767).to(torch.int16).numpy().T
            audio.writeframesraw(samples.astype("<i2", copy=False).tobytes())


def execute(run_id, data_root, model_root, source_root):
    from ai_station_runner.music import PERMISSIONS, MusicRequest

    run_id = str(UUID(run_id))
    data_root = no_symlink(data_root)
    relative = f"runtime/music/{run_id}"
    work_root = resolve_child(data_root, relative)
    if work_root != data_root / relative:
        raise ValueError("Music work directory contains symlinks")
    request = no_symlink(work_root / "request.json")
    if request.stat().st_size > 32768:
        raise ValueError("Music request exceeds its limit")
    body = MusicRequest.model_validate_json(request.read_text())
    if str(body.run_id) != run_id or set(body.permissions) != PERMISSIONS:
        raise ValueError("Music request ownership or permissions changed")
    output_relative = f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.wav"
    output = resolve_child(data_root, output_relative)
    if output != data_root / output_relative or output.exists():
        raise ValueError("Music output exists or contains symlinks")
    signal.alarm(3600)
    parameters = body.model_dump(mode="json")
    tensor = generate(
        parameters, str(no_symlink(model_root)), work_root / "checkpoints", source_root, work_root
    )
    partial = work_root / "output.partial.wav"
    write_pcm(tensor, partial)
    metadata = wav_metadata(partial, requested_seconds=body.duration_seconds)
    output.parent.mkdir(parents=True, exist_ok=True)
    os.link(partial, output)
    partial.unlink()
    signal.alarm(0)
    print(f"Created {metadata['duration_seconds']:.1f}s music WAV on GPU {body.gpu}.", flush=True)


if __name__ == "__main__":
    try:
        execute(*sys.argv[1:])
    except Exception:
        print("Local music failed; inspect its offline preset, runtime and owned Run logs.", file=sys.stderr)
        sys.exit(1)
