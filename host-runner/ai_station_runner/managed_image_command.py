"""Unregistered fixed sd-cli command contract for guided image qualification.

Input prompts are already prepared/frozen by the caller. This helper neither
routes workloads nor grants installation or Docker access; only a qualified
native container lifecycle may use it for application jobs.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImageCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    mode: Literal["t2i", "img2img", "recompose"]
    prompt: str = Field(min_length=1, max_length=10000)
    reference_count: int = Field(default=0, ge=0, le=8)
    width: int = Field(ge=256, le=2048, multiple_of=32)
    height: int = Field(ge=256, le=2048, multiple_of=32)
    steps: int = Field(ge=1, le=150)
    cfg: float = Field(ge=0, le=30, allow_inf_nan=False)
    seed: int = Field(ge=0, le=4294967295)

    @model_validator(mode="after")
    def sources(self):
        if not self.prompt.strip():
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
