"""Fixed offline Sonic inference; imported only inside a verified owned scope.

The upstream installation is read-only. Its original conditioning and diffusion
math remain in use; Station owns exact timing, bounded loading and publication.
"""

import gc
from pathlib import Path

from ai_station_runner.sonic_frames import capture_inputs
from ai_station_runner.sonic_guidance import install_guidance


def generate(runtime, models, portrait, audio, timing, width, height, seed, device_count):
    import torch
    from accelerate import init_empty_weights
    from diffusers import AutoencoderKLTemporalDecoder, EulerDiscreteScheduler
    from omegaconf import OmegaConf
    from sonic import test
    from src.dataset.face_align.align import AlignImage
    from src.dataset.test_preprocess import image_audio_to_tensor
    from src.models.audio_adapter.audio_proj import AudioProjModel
    from src.models.audio_adapter.audio_to_bucket import Audio2bucketModel
    from src.models.base.unet_spatio_temporal_condition import (
        UNetSpatioTemporalConditionModel,
        add_ip_adapters,
    )
    from src.pipelines.pipeline_sonic import SonicPipeline
    from src.utils.util import seed_everything
    from transformers import AutoFeatureExtractor, CLIPVisionModelWithProjection, WhisperModel

    if torch.cuda.device_count() != device_count:
        raise ValueError("Visible devices do not match the allocated avatar GPUs")
    torch.set_num_threads(4)
    seed_everything(seed)
    for index in range(device_count):
        torch.cuda.set_per_process_memory_fraction(0.86, index)
    config = OmegaConf.load(Path(runtime) / "config/inference/sonic.yaml")
    expected = {
        "num_inference_steps": 25,
        "n_sample_frames": 25,
        "fps": 12.5,
        "step": 2,
        "overlap": 0,
        "shift_offset": 7,
        "ip_audio_scale": 1.0,
        "area": 1.1,
        "min_appearance_guidance_scale": 2.0,
        "max_appearance_guidance_scale": 2.0,
        "audio_guidance_scale": 7.5,
        "motion_bucket_scale": 1.0,
        "noise_aug_strength": 0.0,
        "i2i_noise_strength": 1.0,
    }
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError("Installed Sonic configuration does not match the fixed profile")
    config.decode_chunk_size, config.use_interframe = 2, False
    models = Path(models)
    svd = models / "stable-video-diffusion-img2vid-xt"
    extractor = AutoFeatureExtractor.from_pretrained(models / "whisper-tiny", local_files_only=True)
    face = AlignImage("cpu", det_path=str(models / "yoloface_v5m.pt"))
    batch = image_audio_to_tensor(
        face,
        extractor,
        str(portrait),
        str(audio),
        limit=timing.feature_frames,
        image_size=min(width, height),
        area=config.area,
    )
    del face, extractor
    if batch is None:
        raise ValueError("No face detected; choose a clear front-facing portrait")
    if list(batch["ref_img"].shape) != [3, height, width]:
        raise ValueError("Sonic preprocessing changed the frozen portrait geometry")
    # Native preprocessing floors samples/640. Whisper features are already
    # padded; request the ceil-aligned global length so no speech tail is lost.
    batch["audio_len"] = timing.feature_frames
    print("avatar.preparing: complete portrait and audio verified", flush=True)
    with init_empty_weights():
        unet = UNetSpatioTemporalConditionModel.from_config(str(svd / "unet/config.json"))
        add_ip_adapters(unet, [32], [1.0])
    weights = torch.load(models / "Sonic/unet.pth", map_location="cpu", mmap=True, weights_only=True)
    unet.load_state_dict(weights, strict=True, assign=True)
    del weights
    if any(value.is_meta for value in unet.state_dict().values()):
        raise ValueError("Sonic checkpoint contains uninitialized parameters")
    unet.to(dtype=torch.float16).eval().requires_grad_(False)
    for module in unet.modules():
        if hasattr(module, "set_chunk_feed_forward"):
            temporal = type(module).__name__ == "TemporalBasicTransformerBlock"
            module.set_chunk_feed_forward(chunk_size=5, dim=1 if temporal else 0)
    install_guidance(unet, device_count)
    vae = AutoencoderKLTemporalDecoder.from_pretrained(
        svd, subfolder="vae", variant="fp16", torch_dtype=torch.float16, local_files_only=True
    ).eval()
    image_encoder = CLIPVisionModelWithProjection.from_pretrained(
        svd, subfolder="image_encoder", variant="fp16", torch_dtype=torch.float16, local_files_only=True
    ).eval()
    scheduler = EulerDiscreteScheduler.from_pretrained(svd, subfolder="scheduler", local_files_only=True)
    audio_token = AudioProjModel(
        seq_len=10, blocks=5, channels=384, intermediate_dim=1024, output_dim=1024, context_tokens=32
    )
    audio_bucket = Audio2bucketModel(
        seq_len=50,
        blocks=1,
        channels=384,
        clip_channels=1024,
        intermediate_dim=1024,
        output_dim=1,
        context_tokens=2,
    )
    for model, name in ((audio_token, "audio2token"), (audio_bucket, "audio2bucket")):
        model.load_state_dict(
            torch.load(models / f"Sonic/{name}.pth", map_location="cpu", weights_only=True), strict=True
        )
        model.to("cuda").eval().requires_grad_(False)
    whisper = (
        WhisperModel.from_pretrained(models / "whisper-tiny", local_files_only=True)
        .to("cuda")
        .eval()
        .requires_grad_(False)
    )
    pipe = SonicPipeline(unet=unet, image_encoder=image_encoder, vae=vae, scheduler=scheduler)
    # VAE encode() does not invoke Accelerate's forward hooks. Keep it resident.
    # DataParallel also requires the source UNet to remain on primary GPU.
    pipe.model_cpu_offload_seq = "image_encoder" if device_count == 2 else "image_encoder->unet"
    pipe._exclude_from_cpu_offload = ["unet", "vae"] if device_count == 2 else ["vae"]
    pipe.enable_model_cpu_offload(gpu_id=0)
    with torch.no_grad():
        positional, keyword = capture_inputs(
            test,
            torch.device("cuda"),
            config,
            whisper,
            audio_token,
            audio_bucket,
            image_encoder,
            width,
            height,
            batch,
        )
        if keyword.get("num_frames") != timing.base_frames:
            raise ValueError("Sonic audio preparation dropped canonical speech frames")
        # Conditioning is complete. Release unused encoders before diffusion;
        # no second pass or independently restarted short clips are generated.
        for model in (audio_token, audio_bucket, whisper):
            model.to("cpu")
        del audio_token, audio_bucket, whisper, batch
        torch.cuda.empty_cache()
        print(f"avatar.generating: {timing.base_frames} global frames, 25 steps", flush=True)
        frames = pipe(*positional, **keyword).frames
        if list(frames.shape) != [1, 3, timing.base_frames, height, width] or frames.device.type != "cpu":
            raise ValueError("Invalid complete decoded Sonic recording")
        # Normalize the sole complete CPU buffer in place, avoiding the native
        # test helper's multiple full-movie copies and round-trip onto the GPU.
        frames.mul_(0.5).add_(0.5).clamp_(0, 1)
    del pipe, unet, vae, image_encoder, positional, keyword
    gc.collect()  # Forward/offload hooks can retain model-reference cycles.
    torch.cuda.empty_cache()
    return frames


def load_interpolator(models):
    import torch
    from src.utils.RIFE.RIFE_HDv3 import RIFEModel

    model = RIFEModel(device="cpu")
    state = torch.load(Path(models) / "RIFE/flownet.pkl", map_location="cpu", weights_only=True)
    if not state or any(not key.startswith("module.") for key in state):
        raise ValueError("Unexpected RIFE checkpoint layout")
    model.flownet.load_state_dict(
        {key.removeprefix("module."): value for key, value in state.items()}, strict=True
    )
    return model
