"""The candidate command cannot expand a prompt into paths, flags or host devices."""

import pytest
from ai_station_runner.managed_image_command import ImageCommand, argv
from pydantic import ValidationError


def request(**changes):
    return ImageCommand(
        **dict(mode="t2i", prompt="A ceramic mug", width=512, height=512, steps=4, cfg=5.0, seed=42) | changes
    )


def test_prompt_is_one_literal_argument_and_paths_stay_fixed():
    text = '--output /etc/passwd; $(touch /tmp/unwanted)\n" --backend cpu'
    command = argv(request(prompt=text), gpu_count=1)
    assert command[command.index("-p") + 1] == text
    assert command.count(text) == 1
    assert command[command.index("-o") + 1] == "/output/result.png"
    assert "--offload-to-cpu" not in command and "--rpc-servers" not in command
    assert command[command.index("--backend") + 1] == "CUDA0"
    assert command[command.index("--params-backend") + 1] == "CUDA0"
    assert "--llm_vision" not in command


def test_references_are_ordered_fixed_coordinates_and_two_gpu_placement_is_explicit():
    command = argv(request(mode="recompose", reference_count=3), gpu_count=2)
    assert [command[i + 1] for i, value in enumerate(command) if value == "-r"] == [
        "/inputs/0.png",
        "/inputs/1.png",
        "/inputs/2.png",
    ]
    assert command[command.index("--llm_vision") + 1] == "/models/vision.gguf"
    assert command[command.index("--backend") + 1] == "diffusion=CUDA0,te=CUDA1,vae=CUDA0"
    assert command[command.index("--params-backend") + 1] == "diffusion=CUDA0,te=CUDA1,vae=CUDA0"


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "upscale"},
        {"mode": "img2img"},
        {"mode": "recompose"},
        {"reference_count": 1},
        {"mode": "img2img", "reference_count": 2},
        {"mode": "recompose", "reference_count": 9},
        {"width": 513},
        {"height": 8192},
        {"cfg": float("nan")},
        {"steps": True},
        {"seed": -1},
        {"prompt": "  "},
        {"prompt": "invalid\x00instruction"},
        {"image_reference": "unreviewed/image:latest"},
        {"output": "/data/db/application.sqlite"},
    ],
)
def test_invalid_or_unimplemented_operations_and_caller_destinations_are_rejected(changes):
    with pytest.raises(ValidationError):
        request(**changes)


@pytest.mark.parametrize("gpu_count", [0, 3, -1, True, "0,1"])
def test_unsupported_device_counts_never_construct_a_command(gpu_count):
    with pytest.raises(ValueError):
        argv(request(), gpu_count=gpu_count)


def test_upscale_has_one_fixed_input_and_no_generation_or_remote_controls():
    body = ImageCommand(mode="upscale", reference_count=1, width=1268, height=1692)
    command = argv(body, gpu_count=1)
    assert command[:5] == ["/sd-cli", "-M", "upscale", "--upscale-model", "/models/upscaler.pth"]
    assert command[command.index("-i") + 1] == "/inputs/0.png"
    assert command[command.index("--upscale-repeats") + 1] == "1"
    assert command[command.index("--backend") + 1] == "CUDA0"
    assert "-p" not in command and "--llm" not in command and "--offload-to-cpu" not in command
    with pytest.raises(ValueError):
        argv(body, gpu_count=2)


@pytest.mark.parametrize(
    "changes",
    [
        {"width": 8192, "height": 8196},
        {"width": 1269},
        {"reference_count": 2},
        {"prompt": "change something"},
        {"steps": 4},
        {"cfg": 5.0},
        {"seed": 42},
    ],
)
def test_upscale_never_accepts_unbounded_output_or_ignored_generation_options(changes):
    with pytest.raises(ValidationError):
        ImageCommand(**{"mode": "upscale", "reference_count": 1, "width": 1268, "height": 1692, **changes})
