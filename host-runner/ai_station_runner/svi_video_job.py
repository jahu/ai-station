"""One fixed offline SVI Pro window in an owned native process and memory scope."""

import gc
import hashlib
import importlib
import json
import signal
import sys
import time
import types
from pathlib import Path
from uuid import UUID

from ai_station_runner import svi_environment
from ai_station_runner.media_compose_job import source_path
from ai_station_runner.media_encoding import h264_options, video_encoding_metadata
from ai_station_runner.memory_scope import current_group, require_scope
from ai_station_runner.svi_identity import profile_identity
from ai_station_runner.wan_svi_context import FPS, FRAMES, METADATA_KEY, generation_dimensions, motion_shape


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def stage(message):
    print("video.stage: " + message, flush=True)


def main(config_path):
    path = Path(config_path)
    config = json.loads(path.read_text())
    root = Path(config["root"])
    request = config["request"]
    generation_profile = request.get("generation_profile", "landscape")
    width, height = generation_dimensions(generation_profile)
    shape = motion_shape(width, height)
    identity = str(UUID(request["run_id"]))
    work = root / "runs" / identity / "svi"
    if root.resolve() != root or path.resolve() != path or path != work / "request.json":
        raise ValueError("SVI must use its canonical owned native request")
    limits = require_scope(identity, 18432)
    remaining = min(3500, request["deadline_at"] - time.time())
    if remaining <= 0:
        raise TimeoutError("The SVI execution deadline expired")
    signal.setitimer(signal.ITIMER_REAL, remaining)

    def offline(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            raise PermissionError("SVI inference is offline")

    sys.addaudithook(offline)
    stage("verifying frozen SVI inputs")
    selected = svi_environment.resolve_public(root, request["managed_runtime"])
    if Path(sys.base_prefix).resolve() != selected["environment"] / "python":
        raise ValueError("SVI must execute its exact owned Python environment")
    svi_environment.model_paths(
        root, selected["environment"] / "models", svi_environment.recipe(), verify_weights=True
    )
    image_path = source_path(root, request["image"])
    profile = profile_identity(request["managed_runtime"], request["image"]["sha256"], generation_profile)
    if profile != config["profile_identity"]:
        raise ValueError("The frozen SVI implementation or original anchor changed")
    previous_path = None
    if request["previous_motion"] is not None:
        from ai_station_runner.wan_svi_context import validate_checkpoint

        previous_path = source_path(root, request["previous_motion"])
        validate_checkpoint(previous_path, profile, width=width, height=height)
    sys.path.insert(0, str(selected["comfy_dir"]))
    sys.argv = [
        "ai-station-svi",
        "--lowvram",
        "--disable-dynamic-vram",
        "--cache-none",
        "--disable-all-custom-nodes",
        "--disable-api-nodes",
        "--base-directory",
        str(work),
    ]
    import comfy.options

    comfy.options.enable_args_parsing()
    import av
    import comfy.latent_formats
    import comfy.model_management
    import comfy.samplers
    import comfy.sd
    import comfy.utils
    import folder_paths
    import node_helpers
    import nodes
    import numpy as np
    import torch
    from comfy_extras.nodes_model_advanced import ModelSamplingSD3
    from PIL import Image
    from safetensors.torch import load_file, save_file

    from ai_station_runner.wan_svi_adapter import attach
    from ai_station_runner.wan_svi_context import conditioning

    if not torch.cuda.is_available():
        raise ValueError("SVI requires its allocated CUDA device; no CPU fallback")
    package = types.ModuleType("ai_station_svi_gguf")
    package.__path__ = [str(selected["gguf_dir"])]
    sys.modules[package.__name__] = package
    loader = importlib.import_module(package.__name__ + ".nodes")
    model_dir = selected["environment"] / "models"
    folder_paths.folder_names_and_paths["unet"] = ([str(model_dir)], {".gguf"})
    folder_paths.folder_names_and_paths["diffusion_models"] = ([str(model_dir)], {".gguf"})
    folder_paths.folder_names_and_paths["text_encoders"] = ([str(model_dir)], {".safetensors"})
    output = root / "artifacts" / identity[:2] / identity[2:4] / identity
    fmt = comfy.latent_formats.Wan21()
    with torch.inference_mode():
        stage("encoding prompt")
        clip = nodes.CLIPLoader().load_clip(selected["wan_text_encoder"].name, "wan", "cpu")[0]
        positive = nodes.CLIPTextEncode().encode(clip, request["prompt"])[0]
        negative = nodes.CLIPTextEncode().encode(clip, request["negative_prompt"])[0]
        comfy.model_management.unload_all_models()
        del clip
        gc.collect()
        stage("encoding original anchor")
        vae = comfy.sd.VAE(
            sd=comfy.utils.load_torch_file(str(selected["wan_vae"]), safe_load=True), dtype=torch.float32
        )
        with Image.open(image_path) as source:
            pixels = torch.from_numpy(np.array(source.convert("RGB"), dtype=np.float32) / 255).unsqueeze(0)
        pixels = comfy.utils.common_upscale(
            pixels.movedim(-1, 1), width, height, "bilinear", "center"
        ).movedim(1, -1)
        anchor = vae.encode(pixels)
        previous = load_file(str(previous_path), device="cpu")["motion"] if previous_path else None
        raw, mask = conditioning(anchor, previous, fmt, width=width, height=height)
        values = {"concat_latent_image": raw, "concat_mask": mask}
        positive = node_helpers.conditioning_set_values(positive, values)
        negative = node_helpers.conditioning_set_values(negative, values)
        comfy.model_management.unload_all_models()
        gc.collect()
        samples = {"samples": torch.zeros((1, 16, 21, *shape[-2:]), dtype=torch.float32)}
        reports, cut = [], None
        for role in ("high", "low"):
            stage("loading " + role + " expert")
            model = loader.UnetLoaderGGUF().load_unet(
                selected["wan_" + role + "_noise"].name,
                dequant_dtype="bfloat16",
                patch_dtype="float32",
                patch_on_device=False,
            )[0]
            model, adapter = attach(model, selected["svi_" + role + "_adapter"])
            model = ModelSamplingSD3().patch(model, 5.0)[0]
            sigmas = comfy.samplers.calculate_sigmas(model.get_model_object("model_sampling"), "simple", 20)
            boundary = next(index for index, sigma in enumerate(sigmas) if float(sigma) < 0.875)
            if not 0 < boundary < 20 or (cut is not None and boundary != cut):
                raise ValueError("The SVI high/low expert boundary changed")
            cut = boundary
            torch.cuda.reset_peak_memory_stats()
            stage("sampling " + role + " expert")
            samples = nodes.KSamplerAdvanced().sample(
                model,
                "enable" if role == "high" else "disable",
                request["seed"],
                20,
                5,
                "euler",
                "simple",
                positive,
                negative,
                samples,
                0 if role == "high" else cut,
                cut if role == "high" else 20,
                "enable" if role == "high" else "disable",
            )[0]
            if not torch.isfinite(samples["samples"]).all():
                raise ValueError("Non-finite SVI samples")
            reports.append(
                {
                    "role": role,
                    "adapter": adapter,
                    "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(),
                }
            )
            comfy.model_management.unload_all_models()
            del model
            gc.collect()
            torch.cuda.empty_cache()
        motion = output.with_suffix(".safetensors")
        partial = output.with_suffix(".partial.safetensors")
        save_file(
            {"motion": samples["samples"][:, :, -1:].detach().cpu().float().contiguous()},
            str(partial),
            metadata={METADATA_KEY: profile},
        )
        partial.replace(motion)
        stage("decoding frames")
        frames = nodes.VAEDecode().decode(vae, samples)[0]
        if tuple(frames.shape) != (FRAMES, height, width, 3) or not torch.isfinite(frames).all():
            raise ValueError("The fixed SVI output geometry changed")
        final, partial = output.with_suffix(".mp4"), output.with_suffix(".partial.mp4")
        with av.open(str(partial), "w") as container:
            stream = container.add_stream("libx264", rate=FPS)
            stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
            stream.options = h264_options()
            for pixels in frames:
                frame = av.VideoFrame.from_ndarray(
                    (pixels.clamp(0, 1).cpu().numpy() * 255).round().astype(np.uint8), format="rgb24"
                )
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        partial.replace(final)
        report = {
            "backend": "wan22-svi-pro-q4",
            "profile_identity": profile,
            "managed_runtime": request["managed_runtime"],
            "width": width,
            "height": height,
            "frames": FRAMES,
            "fps": FPS,
            "steps": 20,
            "cfg": 5,
            "seed": request["seed"],
            "sampler": "euler",
            "scheduler": "simple",
            "shift": 5,
            "expert_boundary": 0.875,
            "switch_step": cut,
            "expert_reports": reports,
            "video_encoding": video_encoding_metadata(),
            "limits": limits,
            "peak_ram_bytes": int((current_group() / "memory.peak").read_text()),
            "motion_context": {
                "relative_path": motion.relative_to(root).as_posix(),
                "sha256": sha(motion),
                "size_bytes": motion.stat().st_size,
            },
            "output_sha256": sha(final),
        }
        output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
        stage("complete")


if __name__ == "__main__":
    main(sys.argv[1])
