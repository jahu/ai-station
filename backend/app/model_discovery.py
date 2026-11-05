"""Capability-oriented metadata discovery over the existing bounded comparer."""

import asyncio
from typing import Literal

import httpx

from app.hub_sources import parse_source

Capability = Literal["chat", "image", "video", "speech", "music", "avatar", "embedding"]
# These are navigation starting points, not installation/runtime authority. Every
# source is inspected normally, then fitted and reviewed before any download.
STARTING_POINTS = {
    "chat": (
        "Qwen3-4B-GGUF",
        "https://huggingface.co/mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-GGUF/blob/c9e90669eeb205d5af35c28a3e9983fc9293c2ec/Huihui-Qwen3-4B-Instruct-2507-abliterated.Q4_K_M.gguf",
    ),
    "image": (
        "Qwen-Image-2.1",
        "https://huggingface.co/0xSojalSec/Qwen-Image-2.1-Uncensored-GGUF/blob/242be4d1f70cc26fa45773c452f81980ed656e2e/qwen-image-2.1-Q4_K_M.gguf",
    ),
    "video": (
        "Wan-2.2",
        "https://huggingface.co/Comfy-Org/Wan-2.2/blob/ee6f4a40737a995bf5818954cfce6d59443b0f04/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors",
    ),
    "speech": (
        "chatterbox",
        "https://huggingface.co/ResembleAI/chatterbox/blob/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18/t3_mtl23ls_v3.safetensors",
    ),
    "music": (
        "Ace-Step1.5",
        "https://huggingface.co/ACE-Step/Ace-Step1.5/blob/19671f406d603126926c1b7e2adc169acbcade22/acestep-v15-turbo/model.safetensors",
    ),
    "avatar": (
        "Sonic",
        "https://huggingface.co/LeonJoe13/Sonic/blob/3526dc3646480c0ac3f34cada466a88c4771e462/Sonic/unet.pth",
    ),
    "embedding": (
        "multilingual-e5-small",
        "https://huggingface.co/Xenova/multilingual-e5-small/blob/761b726dd34fb83930e26aab4e9ac3899aa1fa78/onnx/model.onnx",
    ),
}


async def recommend(session, run, check, search_models, inspect_source, hardware, storage):
    from app.hub_comparisons import compare_sources

    request = run.parameters["recommendation"]
    capability = request["capability"]
    query, reference = STARTING_POINTS[capability]
    source = parse_source(reference)
    rows = [
        {
            "repository": source.repository,
            "source_url": reference,
            "pipeline_hint": "",
            "downloads": None,
            "starting_point": True,
        }
    ]
    notice = None
    try:
        async with asyncio.timeout(20):
            found = (
                await search_models(query, check, order="recent")
                if request["order"] == "recent"
                else await search_models(query, check)
            )
        for row in found.get("items", []):
            if row["repository"] not in {r["repository"] for r in rows}:
                rows.append(row)
            if len(rows) == 3:
                break
    except (ValueError, httpx.HTTPError, TimeoutError) as exc:
        check()
        notice = "Publisher search is unavailable; the inspected runtime starting point is shown. " + (
            str(exc)[:160] or "Try again later."
        )
    check()
    report = await compare_sources(
        session,
        run,
        check,
        inspect_source,
        hardware,
        storage,
        {"query": query, "items": rows},
        request["context_target"],
        capability=capability,
        allow_file_sources=True,
    )
    return {
        **report,
        "capability": capability,
        "order": request["order"],
        "discovery_notice": notice,
        "note": "Up to three inspected sources for this capability. Starting points are pinned examples; other matches come from publisher search. Hardware fit is an estimate, not a quality benchmark.",
    }
