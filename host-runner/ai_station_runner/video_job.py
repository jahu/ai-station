"""One fixed built-in ComfyUI Wan invocation in an owned native process group."""

import gc
import json
import signal
import sys
from pathlib import Path


def stage(message):
    print(f"video.stage: {message}", flush=True)


def main(config_path):
    config = json.loads(Path(config_path).read_text())
    request, paths, work = config["request"], config["paths"], config["work"]
    signal.alarm(3600)
    sys.path.insert(0, paths["comfy_dir"])
    sys.argv = [
        "ai-station-wan",
        "--lowvram",
        "--disable-dynamic-vram",
        "--cache-none",
        "--disable-all-custom-nodes",
        "--disable-api-nodes",
        "--base-directory",
        work,
    ]
    import comfy.options

    comfy.options.enable_args_parsing()
    import av
    import folder_paths
    import nodes
    import numpy as np
    import torch
    from comfy_extras.nodes_model_advanced import ModelSamplingSD3
    from comfy_extras.nodes_wan import Wan22ImageToVideoLatent
    from PIL import Image

    # Local aliases preserve safetensors names for canonical HF cache blobs.
    aliases = {}
    for category, key in (
        ("diffusion_models", "wan_model"),
        ("text_encoders", "wan_text_encoder"),
        ("vae", "wan_vae"),
    ):
        directory = Path(work) / "selected_models" / category
        directory.mkdir(parents=True)
        alias = directory / "selected.safetensors"
        alias.symlink_to(paths[key])
        aliases[key] = alias.name
        folder_paths.folder_names_and_paths[category] = ([str(directory)], {".safetensors"})
    with torch.inference_mode():
        stage("encoding prompt")
        clip = nodes.CLIPLoader().load_clip(aliases["wan_text_encoder"], "wan", "cpu")[0]
        positive = nodes.CLIPTextEncode().encode(clip, request["prompt"])[0]
        negative = nodes.CLIPTextEncode().encode(clip, request["negative_prompt"])[0]
        del clip
        gc.collect()
        stage("preparing first frame" if config["image"] else "preparing video")
        vae = nodes.VAELoader().load_vae(aliases["wan_vae"])[0]
        image = None
        if config["image"]:
            with Image.open(config["image"]) as source:
                image = torch.from_numpy(np.array(source.convert("RGB"), dtype=np.float32) / 255).unsqueeze(0)
        latent = Wan22ImageToVideoLatent.execute(
            vae, request["width"], request["height"], request["frames"], 1, image
        )[0]
        stage("loading Wan 2.2")
        model = nodes.UNETLoader().load_unet(aliases["wan_model"], "default")[0]
        model = ModelSamplingSD3().patch(model, 8.0)[0]
        stage("generating frames")
        samples = nodes.KSampler().sample(
            model,
            request["seed"],
            request["steps"],
            request["cfg"],
            "uni_pc",
            "simple",
            positive,
            negative,
            latent,
        )[0]
        comfy.model_management.unload_all_models()
        del model
        gc.collect()
        stage("decoding video")
        frames = nodes.VAEDecode().decode(vae, samples)[0]
        if len(frames) != request["frames"] or tuple(frames.shape[1:3]) != (
            request["height"],
            request["width"],
        ):
            raise ValueError("Decoded video does not match requested dimensions/frame count")
        stage("saving MP4")
        output = Path(config["output"])
        temporary = output.with_suffix(".partial.mp4")
        with av.open(str(temporary), "w") as container:
            stream = container.add_stream("libx264", rate=24)
            stream.width, stream.height, stream.pix_fmt = request["width"], request["height"], "yuv420p"
            for pixels in frames:
                pixels = (pixels.clamp(0, 1).cpu().numpy() * 255).round().astype(np.uint8)
                frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        temporary.replace(output)
        stage("completed")


if __name__ == "__main__":
    main(sys.argv[1])
