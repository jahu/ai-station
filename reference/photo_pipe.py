#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import torch
from PIL import Image
from diffusers import AutoPipelineForText2Image


HOME = Path.home()

# ============================================================
# PATHS
# ============================================================

SDCLI = HOME / "AI/src/stable-diffusion.cpp/build/bin/sd-cli"

MODELS = HOME / "AI/models/image"
CACHE_DIR = HOME / "AI/cache/huggingface"
OUT_DIR = HOME / "AI/outputs"
TMP_DIR = HOME / "AI/tmp"

JUGGERNAUT_MODEL_ID = "RunDiffusion/Juggernaut-XL-v9"

UPSCALER = MODELS / "upscalers" / "RealESRGAN_x4plus.pth"


# ============================================================
# QWEN MODELS
# ============================================================

QWEN_DIFFUSION_CANDIDATES = [
    MODELS / "diffusion_models/qwen_image_2.1-Q6_K.gguf",
    MODELS / "diffusion_models/qwen-image-2.1-Q6_K.gguf",

    MODELS / "diffusion_models/qwen-image-2.1-Q4_K_M.gguf",
    MODELS / "diffusion_models/qwen_image_2.1-Q4_K_M.gguf",
    MODELS / "diffusion_models/qwen_image_2.1-Q4_K.gguf",
]

QWEN_VAE_CANDIDATES = [
    MODELS / "vae/qwen_image_2.1_vae_bf16.safetensors",
]

QWEN_LLM_CANDIDATES = [
    MODELS / "text_encoders/Qwen3VL-8B-Instruct-Q4_K_M.gguf",
]

QWEN_MMPROJ_CANDIDATES = [
    MODELS / "text_encoders/mmproj-Qwen3VL-8B-Instruct-F16.gguf",
]


# ============================================================
# PROMPTS
# ============================================================

PHOTO_SUFFIX = """
photorealistic RAW photograph,
natural realistic skin,
subtle visible skin pores,
natural skin imperfections,
fine facial detail,
realistic hair strands,
realistic eyes,
physically accurate natural lighting,
natural shadows,
realistic material textures,
DSLR photography,
50mm lens,
natural depth of field,
subtle realistic color grading
""".replace("\n", " ").strip()

T2I_NEGATIVE = """
cgi,
3d render,
cartoon,
anime,
painting,
illustration,
digital art,
plastic skin,
waxy skin,
oversmoothed skin,
airbrushed skin,
fake skin,
uncanny face,
deformed face,
bad anatomy,
deformed hands,
extra fingers,
blurry,
low resolution
""".replace("\n", " ").strip()

IDENTITY_PREFIX = """
Preserve the exact identity of the person in the source image.
Do not change the person's face.
Preserve exact facial geometry and recognizable identity.
Preserve face shape, forehead, eyes, eye spacing, eyebrows,
nose shape, lips, mouth shape, jawline, chin, ears and skin tone.
Preserve hairstyle, hairline and apparent age.
Preserve natural skin texture and existing facial details.
Do not smooth, beautify, retouch, stylize or redesign the face or skin.
Preserve body proportions unless explicitly requested otherwise.
Preserve pose, camera angle, perspective and overall composition.
Do not unnecessarily modify any part of the image.
The result must clearly depict the exact same person.
Only perform the requested change:
""".replace("\n", " ").strip()

RECOMPOSE_PREFIX_SINGLE = """
Use the reference image as an identity reference for the main person.

Preserve the exact facial identity of the person.
Preserve recognizable face shape, eyes, eyebrows, nose, lips, jawline,
skin tone, hairstyle, hairline and apparent age.

Preserve the person's general physique, build, body proportions and overall silhouette.

You are allowed to freely redesign and change:
- pose
- body position
- clothing
- environment
- background
- camera angle
- framing
- lighting
- props
- other people
- activity
- scene composition

Do not preserve the original pose or background unless explicitly requested.
Create a completely new scene if needed, while keeping the same recognizable person.

Create this new scene:
""".replace("\n", " ").strip()

RECOMPOSE_PREFIX_MULTI = """
Use all provided reference images as identity references for the same main person.

Preserve the exact facial identity of that person.
Preserve recognizable face shape, eyes, eyebrows, nose, lips, jawline,
skin tone, hairstyle, hairline and apparent age.

Preserve the person's general physique, build, body proportions and overall silhouette.

Synthesize a coherent depiction of the same person using all reference images together.

You are allowed to freely redesign and change:
- pose
- body position
- clothing
- environment
- background
- camera angle
- framing
- lighting
- props
- other people
- activity
- scene composition

Do not preserve the original pose or background unless explicitly requested.
Create a completely new scene if needed, while keeping the same recognizable person.

Create this new scene:
""".replace("\n", " ").strip()


torch.backends.cuda.matmul.allow_tf32 = True


# ============================================================
# HELPERS
# ============================================================

def ensure_dirs():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def output_path(prefix):
    return OUT_DIR / f"{prefix}_{timestamp()}.png"


def pick_existing(candidates, name):
    for path in candidates:
        if path.exists():
            print(f"[MODEL] {name}: {path}")
            return path

    raise FileNotFoundError(
        f"\nNie znaleziono modelu: {name}\n\n"
        + "Sprawdzone lokalizacje:\n"
        + "\n".join(str(x) for x in candidates)
    )


def round32(value):
    return max(32, int(round(value / 32.0) * 32))


def normalize_qwen_dims(width, height):
    w = round32(width)
    h = round32(height)

    if w != width or h != height:
        print()
        print("[QWEN] Resolution adjusted to multiples of 32")
        print(f"Requested: {width}x{height}")
        print(f"Using:     {w}x{h}")
        print()

    return w, h


def calculate_processing_size(image_path, max_side=1216):
    """
    Zachowuje proporcje oryginalnego zdjęcia.
    Nie upscaluje obrazu wejściowego.
    Ogranicza dłuższy bok do max_side.
    """

    with Image.open(image_path) as img:
        original_w, original_h = img.size

    longest = max(original_w, original_h)

    if longest > max_side:
        scale = max_side / longest
    else:
        scale = 1.0

    width = round32(original_w * scale)
    height = round32(original_h * scale)

    print()
    print("==========================================")
    print("IMAGE SIZE")
    print("==========================================")
    print(f"Original:   {original_w} x {original_h}")
    print(f"Processing: {width} x {height}")
    print("==========================================")
    print()

    return width, height


def get_gpu_index(device):
    if ":" in device:
        return device.split(":")[1]
    return "0"


def print_image_size(path, label):
    try:
        with Image.open(path) as img:
            print(f"{label}: {img.width}x{img.height}")
    except Exception:
        pass


def flatten_reference_args(reference_lists):
    refs = []
    for item in reference_lists:
        if isinstance(item, list):
            refs.extend(item)
        else:
            refs.append(item)
    return refs


# ============================================================
# JUGGERNAUT T2I
# ============================================================

def load_juggernaut_t2i_pipeline(device, cpu_offload):
    print()
    print("[JUGGERNAUT] Loading text-to-image pipeline...")

    pipe = AutoPipelineForText2Image.from_pretrained(
        JUGGERNAUT_MODEL_ID,
        torch_dtype=torch.float16,
        variant="fp16",
        use_safetensors=True,
        cache_dir=str(CACHE_DIR),
    )

    pipe.enable_attention_slicing()

    if hasattr(pipe, "vae"):
        pipe.vae.enable_tiling()
        pipe.vae.enable_slicing()

    if cpu_offload:
        print("[JUGGERNAUT] CPU offload enabled")
        pipe.enable_model_cpu_offload()
    else:
        pipe.to(device)

    return pipe


def run_juggernaut_t2i(
    prompt,
    negative,
    device,
    cpu_offload,
    width,
    height,
    steps,
    cfg,
    seed,
    out,
):
    pipe = load_juggernaut_t2i_pipeline(device, cpu_offload)

    final_prompt = f"{prompt.strip()}, {PHOTO_SUFFIX}"

    generator_device = device if device.startswith("cuda") else "cpu"
    generator = torch.Generator(device=generator_device).manual_seed(seed)

    print()
    print("==========================================")
    print("TEXT TO IMAGE - JUGGERNAUT")
    print("==========================================")
    print(f"Resolution: {width}x{height}")
    print(f"Steps:      {steps}")
    print(f"CFG:        {cfg}")
    print(f"Seed:       {seed}")
    print()
    print("Prompt:")
    print(final_prompt)
    print()

    with torch.inference_mode():
        image = pipe(
            prompt=final_prompt,
            negative_prompt=negative,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=cfg,
            generator=generator,
        ).images[0]

    image.save(out)


# ============================================================
# QWEN T2I
# ============================================================

def run_qwen_t2i(
    prompt,
    device,
    width,
    height,
    steps,
    cfg,
    out,
):
    diffusion_model = pick_existing(QWEN_DIFFUSION_CANDIDATES, "Qwen diffusion")
    vae = pick_existing(QWEN_VAE_CANDIDATES, "Qwen VAE")
    llm = pick_existing(QWEN_LLM_CANDIDATES, "Qwen LLM")

    if not SDCLI.exists():
        raise FileNotFoundError(f"Nie znaleziono sd-cli:\n{SDCLI}")

    width, height = normalize_qwen_dims(width, height)
    final_prompt = f"{prompt.strip()}, {PHOTO_SUFFIX}"

    command = [
        str(SDCLI),
        "--diffusion-model", str(diffusion_model),
        "--vae", str(vae),
        "--llm", str(llm),
        "-p", final_prompt,
        "--cfg-scale", str(cfg),
        "--sampling-method", "euler",
        "--steps", str(steps),
        "--offload-to-cpu",
        "-W", str(width),
        "-H", str(height),
        "-o", str(out),
    ]

    env = os.environ.copy()
    gpu_idx = get_gpu_index(device)
    env["CUDA_VISIBLE_DEVICES"] = gpu_idx

    print()
    print("==========================================")
    print("TEXT TO IMAGE - QWEN")
    print("==========================================")
    print(f"Resolution: {width}x{height}")
    print(f"Steps:      {steps}")
    print(f"CFG:        {cfg}")
    print(f"GPU:        {gpu_idx}")
    print()
    print("Prompt:")
    print(final_prompt)
    print()

    subprocess.run(command, check=True, env=env)

    if not Path(out).exists():
        raise RuntimeError("Qwen nie utworzył pliku wynikowego.")


# ============================================================
# QWEN IMG2IMG
# ============================================================

def run_qwen_edit(
    input_image,
    user_edit_prompt,
    device,
    width,
    height,
    steps,
):
    diffusion_model = pick_existing(QWEN_DIFFUSION_CANDIDATES, "Qwen diffusion")
    vae = pick_existing(QWEN_VAE_CANDIDATES, "Qwen VAE")
    llm = pick_existing(QWEN_LLM_CANDIDATES, "Qwen LLM")
    mmproj = pick_existing(QWEN_MMPROJ_CANDIDATES, "Qwen vision mmproj")

    if not SDCLI.exists():
        raise FileNotFoundError(f"Nie znaleziono sd-cli:\n{SDCLI}")

    width, height = normalize_qwen_dims(width, height)
    final_edit_prompt = f"{IDENTITY_PREFIX} {user_edit_prompt.strip()}"
    intermediate = TMP_DIR / f"qwen_edit_{timestamp()}.png"

    command = [
        str(SDCLI),
        "--diffusion-model", str(diffusion_model),
        "--vae", str(vae),
        "--llm", str(llm),
        "--llm_vision", str(mmproj),
        "-r", str(input_image),
        "-p", final_edit_prompt,
        "--cfg-scale", "6",
        "--sampling-method", "euler",
        "--steps", str(steps),
        "--offload-to-cpu",
        "-W", str(width),
        "-H", str(height),
        "-o", str(intermediate),
    ]

    env = os.environ.copy()
    gpu_idx = get_gpu_index(device)
    env["CUDA_VISIBLE_DEVICES"] = gpu_idx

    print()
    print("==========================================")
    print("QWEN IMG2IMG")
    print("==========================================")
    print(f"GPU:    {gpu_idx}")
    print(f"Output: {intermediate}")
    print()
    print("Prompt:")
    print(final_edit_prompt)
    print()

    subprocess.run(command, check=True, env=env)

    if not intermediate.exists():
        raise RuntimeError("Qwen nie utworzył pliku wynikowego.")

    return intermediate


# ============================================================
# QWEN RECOMPOSE
# ============================================================

def run_qwen_recompose(
    reference_images,
    user_prompt,
    device,
    width,
    height,
    steps,
    cfg,
    out,
):
    diffusion_model = pick_existing(QWEN_DIFFUSION_CANDIDATES, "Qwen diffusion")
    vae = pick_existing(QWEN_VAE_CANDIDATES, "Qwen VAE")
    llm = pick_existing(QWEN_LLM_CANDIDATES, "Qwen LLM")
    mmproj = pick_existing(QWEN_MMPROJ_CANDIDATES, "Qwen vision mmproj")

    if not SDCLI.exists():
        raise FileNotFoundError(f"Nie znaleziono sd-cli:\n{SDCLI}")

    width, height = normalize_qwen_dims(width, height)

    if len(reference_images) == 1:
        prefix = RECOMPOSE_PREFIX_SINGLE
    else:
        prefix = RECOMPOSE_PREFIX_MULTI

    final_prompt = f"{prefix} {user_prompt.strip()}, {PHOTO_SUFFIX}"

    command = [
        str(SDCLI),
        "--diffusion-model", str(diffusion_model),
        "--vae", str(vae),
        "--llm", str(llm),
        "--llm_vision", str(mmproj),
    ]

    for ref in reference_images:
        command.extend(["-r", str(ref)])

    command.extend([
        "-p", final_prompt,
        "--cfg-scale", str(cfg),
        "--sampling-method", "euler",
        "--steps", str(steps),
        "--offload-to-cpu",
        "-W", str(width),
        "-H", str(height),
        "-o", str(out),
    ])

    env = os.environ.copy()
    gpu_idx = get_gpu_index(device)
    env["CUDA_VISIBLE_DEVICES"] = gpu_idx

    print()
    print("==========================================")
    print("QWEN RECOMPOSE")
    print("==========================================")
    print(f"GPU:        {gpu_idx}")
    print(f"References: {len(reference_images)}")
    print(f"Resolution: {width}x{height}")
    print(f"Steps:      {steps}")
    print(f"CFG:        {cfg}")
    print()

    for i, ref in enumerate(reference_images, start=1):
        print(f"Reference {i}: {ref}")

    print()
    print("Prompt:")
    print(final_prompt)
    print()

    subprocess.run(command, check=True, env=env)

    if not Path(out).exists():
        raise RuntimeError("Qwen nie utworzył pliku wynikowego.")


# ============================================================
# REAL-ESRGAN UPSCALE
# ============================================================

def run_upscale(
    input_image,
    out,
    device,
    repeats=1,
):
    if not SDCLI.exists():
        raise FileNotFoundError(f"Nie znaleziono sd-cli:\n{SDCLI}")

    if not UPSCALER.exists():
        raise FileNotFoundError(
            "\nNie znaleziono RealESRGAN:\n"
            f"{UPSCALER}\n\n"
            "Pobierz go komendą:\n\n"
            "wget "
            "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/"
            "RealESRGAN_x4plus.pth "
            f"-O {UPSCALER}"
        )

    input_image = Path(input_image).expanduser()

    if not input_image.exists():
        raise FileNotFoundError(f"Nie znaleziono obrazu:\n{input_image}")

    out = Path(out).expanduser()

    command = [
        str(SDCLI),
        "-M", "upscale",
        "--upscale-model", str(UPSCALER),
        "--upscale-repeats", str(repeats),
        "-i", str(input_image),
        "-o", str(out),
    ]

    env = os.environ.copy()
    gpu_idx = get_gpu_index(device)
    env["CUDA_VISIBLE_DEVICES"] = gpu_idx

    print()
    print("==========================================")
    print("REAL-ESRGAN UPSCALE")
    print("==========================================")
    print_image_size(input_image, "Input")
    print(f"GPU:     {gpu_idx}")
    print(f"Repeats: {repeats}")
    print()

    subprocess.run(command, check=True, env=env)

    if not out.exists():
        raise RuntimeError("RealESRGAN nie utworzył obrazu.")

    print()
    print_image_size(out, "Output")


# ============================================================
# MODES
# ============================================================

def t2i(args):
    ensure_dirs()

    out = Path(args.out).expanduser() if args.out else output_path(f"t2i_{args.backend}")

    if args.backend == "juggernaut":
        negative = args.negative if args.negative else T2I_NEGATIVE

        run_juggernaut_t2i(
            prompt=args.prompt,
            negative=negative,
            device=args.device,
            cpu_offload=args.cpu_offload,
            width=args.width,
            height=args.height,
            steps=args.steps,
            cfg=args.cfg,
            seed=args.seed,
            out=out,
        )

    elif args.backend == "qwen":
        run_qwen_t2i(
            prompt=args.prompt,
            device=args.device,
            width=args.width,
            height=args.height,
            steps=args.steps,
            cfg=args.cfg,
            out=out,
        )

    print()
    print("==========================================")
    print("DONE")
    print("==========================================")
    print(out)


def img2img(args):
    ensure_dirs()

    input_image = Path(args.input).expanduser()

    if not input_image.exists():
        raise FileNotFoundError(f"Nie znaleziono input image:\n{input_image}")

    out = Path(args.out).expanduser() if args.out else output_path("img2img_qwen")

    width, height = calculate_processing_size(
        input_image,
        max_side=args.max_side,
    )

    qwen_result = run_qwen_edit(
        input_image=input_image,
        user_edit_prompt=args.edit_prompt,
        device=args.device,
        width=width,
        height=height,
        steps=args.qwen_steps,
    )

    shutil.copy2(qwen_result, out)

    print()
    print("==========================================")
    print("DONE")
    print("==========================================")
    print_image_size(input_image, "Original")
    print_image_size(out, "Final")
    print()
    print(f"Qwen tmp: {qwen_result}")
    print(f"Final:    {out}")


def recompose(args):
    ensure_dirs()

    reference_args = flatten_reference_args(args.reference)
    reference_images = [Path(x).expanduser() for x in reference_args]

    if not reference_images:
        raise ValueError("Musisz podać przynajmniej jeden --reference")

    for ref in reference_images:
        if not ref.exists():
            raise FileNotFoundError(f"Nie znaleziono reference image:\n{ref}")

    out = Path(args.out).expanduser() if args.out else output_path("recompose_qwen")

    run_qwen_recompose(
        reference_images=reference_images,
        user_prompt=args.prompt,
        device=args.device,
        width=args.width,
        height=args.height,
        steps=args.steps,
        cfg=args.cfg,
        out=out,
    )

    print()
    print("==========================================")
    print("DONE")
    print("==========================================")
    print_image_size(out, "Final")
    print(out)


def upscale(args):
    ensure_dirs()

    input_image = Path(args.input).expanduser()

    out = Path(args.out).expanduser() if args.out else output_path("upscale")

    run_upscale(
        input_image=input_image,
        out=out,
        device=args.device,
        repeats=args.repeats,
    )

    print()
    print("==========================================")
    print("DONE")
    print("==========================================")
    print(out)


# ============================================================
# CLI
# ============================================================

def build_parser():
    parser = argparse.ArgumentParser(
        description="Local image pipeline: Qwen, Juggernaut and RealESRGAN"
    )

    subparsers = parser.add_subparsers(
        dest="mode",
        required=True,
    )

    # --------------------------------------------------------
    # T2I
    # --------------------------------------------------------

    p = subparsers.add_parser(
        "t2i",
        help="Generate new image",
    )

    p.add_argument(
        "--backend",
        choices=["juggernaut", "qwen"],
        default="qwen",
    )

    p.add_argument(
        "--prompt",
        required=True,
    )

    p.add_argument(
        "--negative",
        default=None,
    )

    p.add_argument(
        "--width",
        type=int,
        default=832,
    )

    p.add_argument(
        "--height",
        type=int,
        default=1216,
    )

    p.add_argument(
        "--steps",
        type=int,
        default=35,
    )

    p.add_argument(
        "--cfg",
        type=float,
        default=5.0,
    )

    p.add_argument(
        "--seed",
        type=int,
        default=42,
    )

    p.add_argument(
        "--device",
        default="cuda:0",
    )

    p.add_argument(
        "--cpu-offload",
        action="store_true",
    )

    p.add_argument(
        "--out",
        default=None,
    )

    p.set_defaults(func=t2i)

    # --------------------------------------------------------
    # IMG2IMG
    # --------------------------------------------------------

    p = subparsers.add_parser(
        "img2img",
        help="Edit existing image using Qwen, preserving almost everything",
    )

    p.add_argument(
        "--input",
        required=True,
    )

    p.add_argument(
        "--edit-prompt",
        required=True,
    )

    p.add_argument(
        "--max-side",
        type=int,
        default=1216,
    )

    p.add_argument(
        "--qwen-steps",
        type=int,
        default=30,
    )

    p.add_argument(
        "--device",
        default="cuda:0",
    )

    p.add_argument(
        "--out",
        default=None,
    )

    p.set_defaults(func=img2img)

    # --------------------------------------------------------
    # RECOMPOSE
    # --------------------------------------------------------

    p = subparsers.add_parser(
        "recompose",
        help="Create a new scene while preserving identity of the referenced person",
    )

    p.add_argument(
        "--reference",
        required=True,
        action="append",
        nargs="+",
        help="One or more reference images; repeat --reference if needed",
    )

    p.add_argument(
        "--prompt",
        required=True,
        help="Describe the new scene to create",
    )

    p.add_argument(
        "--width",
        type=int,
        default=832,
    )

    p.add_argument(
        "--height",
        type=int,
        default=1216,
    )

    p.add_argument(
        "--steps",
        type=int,
        default=30,
    )

    p.add_argument(
        "--cfg",
        type=float,
        default=6.0,
    )

    p.add_argument(
        "--device",
        default="cuda:0",
    )

    p.add_argument(
        "--out",
        default=None,
    )

    p.set_defaults(func=recompose)

    # --------------------------------------------------------
    # UPSCALE
    # --------------------------------------------------------

    p = subparsers.add_parser(
        "upscale",
        help="4x upscale using RealESRGAN",
    )

    p.add_argument(
        "--input",
        required=True,
    )

    p.add_argument(
        "--device",
        default="cuda:0",
    )

    p.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Number of x4 passes; normally keep at 1",
    )

    p.add_argument(
        "--out",
        default=None,
    )

    p.set_defaults(func=upscale)

    return parser


# ============================================================
# MAIN
# ============================================================

def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.func(args)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)

    except Exception as exc:
        print()
        print("==========================================")
        print("ERROR")
        print("==========================================")
        print(exc)
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
