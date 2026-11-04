"""Fixed sd-cli command contract for the qualified guided image profile.

Input prompts are already prepared/frozen by the caller. This helper neither
routes workloads nor grants installation or Docker access; only a qualified
native container lifecycle may use it for application jobs.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImageCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    mode: Literal["t2i", "img2img", "recompose", "upscale"]
    prompt: str = Field(default="", max_length=10000)
    reference_count: int = Field(default=0, ge=0, le=8)
    width: int = Field(ge=4, le=32768)
    height: int = Field(ge=4, le=32768)
    steps: int | None = Field(default=None, ge=1, le=150)
    cfg: float | None = Field(default=None, ge=0, le=30, allow_inf_nan=False)
    seed: int | None = Field(default=None, ge=0, le=4294967295)

    @model_validator(mode="after")
    def sources(self):
        if self.mode == "upscale":
            if (
                self.prompt
                or self.reference_count != 1
                or any(v is not None for v in (self.steps, self.cfg, self.seed))
                or self.width % 4
                or self.height % 4
                or self.width * self.height > 64 * 1024**2
            ):
                raise ValueError(
                    "Upscale requires one source and bounded exact 4x dimensions, without generation controls"
                )
            return self
        if (
            any(v is None for v in (self.steps, self.cfg, self.seed))
            or not (256 <= self.width <= 2048 and 256 <= self.height <= 2048)
            or self.width % 32
            or self.height % 32
        ):
            raise ValueError("Generation needs its bounded dimensions, steps, CFG and seed")
        if not self.prompt.strip() or "\x00" in self.prompt:
            raise ValueError("An effective image instruction is required")
        if (
            self.mode == "t2i"
            and self.reference_count != 0
            or self.mode == "img2img"
            and self.reference_count != 1
            or self.mode == "recompose"
            and self.reference_count < 1
        ):
            raise ValueError("Image references must match the selected operation")
        return self


def argv(body: ImageCommand, *, gpu_count: int) -> list[str]:
    """Only fixed container coordinates; physical GPU allocation lives outside argv."""
    if type(gpu_count) is not int or gpu_count not in {1, 2}:
        raise ValueError("Select one or two allocated CUDA GPUs")
    if body.mode == "upscale":
        if gpu_count != 1:
            raise ValueError("Upscale uses exactly one allocated GPU")
        return [
            "/sd-cli",
            "-M",
            "upscale",
            "--upscale-model",
            "/models/upscaler.pth",
            "--upscale-repeats",
            "1",
            "--upscale-tile-size",
            "128",
            "--backend",
            "CUDA0",
            "--params-backend",
            "CUDA0",
            "-i",
            "/inputs/0.png",
            "-o",
            "/output/result.png",
        ]
    placement = "diffusion=CUDA0,te=CUDA1,vae=CUDA0" if gpu_count == 2 else "CUDA0"
    result = [
        "/sd-cli",
        "-M",
        "img_gen",
        "--diffusion-model",
        "/models/diffusion.gguf",
        "--llm",
        "/models/text.gguf",
        "--vae",
        "/models/vae.safetensors",
        "--tensor-type-rules",
        r"^vae\.=f16",
        "--backend",
        placement,
        "--params-backend",
        placement,
        "--sampling-method",
        "euler",
        "--steps",
        str(body.steps),
        "--cfg-scale",
        str(body.cfg),
        "-s",
        str(body.seed),
        "-W",
        str(body.width),
        "-H",
        str(body.height),
        "-p",
        body.prompt,
        "-o",
        "/output/result.png",
    ]
    if body.reference_count:
        result.extend(("--llm_vision", "/models/vision.gguf"))
        for index in range(body.reference_count):
            result.extend(("-r", f"/inputs/{index}.png"))
    return result
