"""Executed by the configured EchoMimic Python, not the Runner environment.

Reuse its inference entry point with a pipeline subclass implementing the CPU
offload mode that infer_flash.py declares but does not apply. No external files
are patched; both upstream .to(device) calls become idempotent offload setup.
"""

import argparse
import importlib
import os
import sys
from contextlib import nullcontext
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--previous-video")
    parser.add_argument("--previous-hash")
    parser.add_argument("--motion-context")
    parser.add_argument("--motion-hash")
    parser.add_argument("--motion-output")
    parser.add_argument("--motion-profile")
    parser.add_argument("--motion-relative")
    parser.add_argument("--station-mapped-run-id")
    options, arguments = parser.parse_known_args()
    if options.station_mapped_run_id:
        from ai_station_runner.echo_loading import qualification_scope

        qualification_scope(options.station_mapped_run_id)
    sys.path.insert(0, options.runtime_dir)
    inference = importlib.import_module("infer_flash")
    base = inference.WanFunInpaintAudioPipeline
    motion = None
    size = int(arguments[arguments.index("--sample_size") + 1])
    from ai_station_runner.echo_motion import flow_sigma, profile_key, validate_checkpoint

    model_root = Path(arguments[arguments.index("--model_name") + 1]).parent
    if options.motion_output and profile_key(options.runtime_dir, model_root) != options.motion_profile:
        raise ValueError("Avatar model/config observation changed before inference")

    if options.motion_context:
        import hashlib

        import torch
        from safetensors.torch import load_file

        path = Path(options.motion_context)
        validate_checkpoint(path, size, options.motion_profile)
        if hashlib.sha256(path.read_bytes()).hexdigest() != options.motion_hash:
            raise ValueError("Avatar latent motion content changed")
        motion = load_file(str(path), device="cpu")["motion"]
        if not torch.isfinite(motion).all():
            raise ValueError("Non-finite avatar motion checkpoint")

    motion_prefix = motion[:, :, -5:] if motion is not None else None

    class OffloadedPipeline(base):
        def to(self, *args, **kwargs):
            if not getattr(self, "_station_offloaded", False):
                self._station_offloaded = True
                self.enable_sequential_cpu_offload(gpu_id=0)
            return self

        def prepare_latents(self, *args, **kwargs):
            latents = super().prepare_latents(*args, **kwargs)
            if motion is not None:
                self._station_motion_noise = latents[:, :, :5].clone()
                skipped = int(arguments[arguments.index("--num_skip_start_steps") + 1])
                sigma = flow_sigma(self.scheduler, skipped)
                latents[:, :, :5] = (1 - sigma) * motion_prefix.to(
                    device=latents.device, dtype=latents.dtype
                ) + sigma * self._station_motion_noise
            return latents

        def __call__(self, *args, **kwargs):
            if motion is not None:
                previous_callback = kwargs.get("callback_on_step_end")

                def preserve_context(pipeline, index, timestep, values):
                    if previous_callback is not None:
                        values = previous_callback(pipeline, index, timestep, values)
                    latents = values["latents"]
                    sigma = flow_sigma(self.scheduler, self.scheduler.step_index)
                    latents[:, :, :5] = (1 - sigma) * motion_prefix.to(
                        device=latents.device, dtype=latents.dtype
                    ) + sigma * self._station_motion_noise
                    return values

                kwargs["callback_on_step_end"] = preserve_context
                kwargs["callback_on_step_end_tensor_inputs"] = ["latents"]
            return super().__call__(*args, **kwargs)

        def prepare_mask_latents(self, mask, masked_image, *args, **kwargs):
            if motion is not None:
                device = kwargs.get("device", args[4] if len(args) > 4 else None)
                decoded = (
                    self.vae.decode(motion.to(device=device, dtype=self.vae.dtype))
                    .sample[:, :, -17:]
                    .clamp(-1, 1)
                )
                if (
                    masked_image is None
                    or decoded.shape[:3] != (1, 3, 17)
                    or decoded.shape[-2:] != masked_image.shape[-2:]
                ):
                    raise ValueError("Avatar decoded motion shape changed")
                masked_image = masked_image.clone()
                masked_image[:, :, :17] = decoded.to(device=masked_image.device, dtype=masked_image.dtype)
            mask, masked = super().prepare_mask_latents(mask, masked_image, *args, **kwargs)
            if motion is not None:
                if (
                    masked is None
                    or masked.shape[:2] != motion_prefix.shape[:2]
                    or masked.shape[-2:] != motion_prefix.shape[-2:]
                    or masked.shape[2] < 5
                ):
                    raise ValueError("Avatar masked latent shape changed")
                masked[:, :, :5] = motion_prefix.to(device=masked.device, dtype=masked.dtype)
            return mask, masked

        def decode_latents(self, latents):
            import torch

            history = (
                motion[:, :, :-5].to(device=latents.device, dtype=latents.dtype)
                if motion is not None
                else None
            )
            combined = torch.cat([history, latents], dim=2) if history is not None else latents
            if options.motion_output:
                import torch
                from safetensors.torch import save_file

                path = Path(options.motion_output)
                partial = path.with_suffix(".partial.safetensors")
                if path.exists() or partial.exists():
                    raise FileExistsError(path)
                if profile_key(options.runtime_dir, model_root) != options.motion_profile:
                    raise ValueError("Avatar model/config observation changed during inference")
                context = combined[:, :, -21:].detach().cpu().float().contiguous()
                if not torch.isfinite(context).all():
                    raise ValueError("Non-finite generated avatar motion")
                save_file(
                    {"motion": context},
                    str(partial),
                    metadata={"station.echo_profile": options.motion_profile},
                )
                validate_checkpoint(partial, size, options.motion_profile)
                partial.chmod(0o600)
                partial.replace(path)
            frames = super().decode_latents(combined)
            return frames[:, :, history.shape[2] * 4 :] if history is not None else frames

    if options.previous_video:
        import hashlib

        digest = hashlib.sha256()
        with Path(options.previous_video).open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != options.previous_hash:
            raise ValueError("Avatar motion context content changed")
        original = inference.get_image_to_video_latent2

        def continued_latents(*args, **kwargs):
            from collections import deque

            import av
            import numpy as np
            import torch

            video, mask, identity = original(*args, **kwargs)
            if motion is not None:
                video[:, :, :17] = 0
                mask[:, :, :17] = 0
                return video, mask, identity
            frames = deque(maxlen=17)
            count = 0
            with av.open(options.previous_video) as source:
                for frame in source.decode(video=0):
                    if (frame.height, frame.width) != tuple(video.shape[-2:]):
                        raise ValueError("Avatar motion context dimensions changed")
                    frames.append(frame.to_ndarray(format="rgb24"))
                    count += 1
                    if count > 81:
                        raise ValueError("Avatar motion context exceeds a native window")
            if len(frames) < 17:
                raise ValueError("Avatar continuation needs seventeen motion frames")
            context = torch.from_numpy(np.stack(list(frames))).permute(3, 0, 1, 2).unsqueeze(0) / 255
            video[:, :, :17] = context.to(dtype=video.dtype)
            mask[:, :, :17] = 0
            return video, mask, identity

        inference.get_image_to_video_latent2 = continued_latents

    inference.WanFunInpaintAudioPipeline = OffloadedPipeline
    sys.argv = [sys.argv[0], *arguments]
    loading = nullcontext()
    if options.station_mapped_run_id:
        from ai_station_runner.echo_loading import mapped_loading

        loading = mapped_loading(inference, model_root)
    with loading:
        inference.main()
    output = Path(options.output_path)
    image = Path(arguments[arguments.index("--image_path") + 1])
    directory = Path(arguments[arguments.index("--save_path") + 1])
    generated = directory / f"{image.name.split('.')[0]}_output.mp4"
    # Decode the actual container before publishing a successful artifact.
    from moviepy import VideoFileClip

    with VideoFileClip(str(generated)) as clip:
        if clip.duration <= 0 or clip.audio is None:
            raise ValueError("Expected a playable video with an audio track")
        clip.get_frame(0)
    if output.exists():
        raise FileExistsError(output)
    os.rename(generated, output)
    if options.motion_output:
        import hashlib
        import json

        checkpoint = Path(options.motion_output)
        output.with_suffix(".json").write_text(
            json.dumps(
                {
                    "motion_context": {
                        "relative_path": options.motion_relative,
                        "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                        "size_bytes": checkpoint.stat().st_size,
                        "context_frames": 17,
                    },
                    "motion_prefix_preserved": motion is not None,
                    "motion_context_source": "latents"
                    if motion is not None
                    else "pixels"
                    if options.previous_video
                    else "initial",
                }
            )
        )


if __name__ == "__main__":
    main()
