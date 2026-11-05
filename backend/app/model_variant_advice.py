"""One pinned configuration, bounded local assessment of its file variants."""

import httpx

from app.hub_candidates import candidate_from_profile, resolve_profile
from app.model_hardware import assess_file

POLICY = "gpu-balanced-v1"
# A preference within one publisher/model, not a cross-model quality benchmark.
BALANCED = {
    name: score
    for score, name in enumerate(
        reversed(
            (
                "Q6_K",
                "Q5_K_M",
                "Q5_K_S",
                "Q5_0",
                "Q4_K_M",
                "Q8_0",
                "Q4_K_S",
                "Q4_0",
                "F16",
                "BF16",
                "F32",
                "IQ4_XS",
                "IQ4_NL",
                "Q3_K_M",
                "Q3_K_S",
                "Q2_K",
                "IQ2_XS",
            )
        ),
        1,
    )
}


async def enrich_source(report, check):
    if len(report["files"]) == 1 and report["files"][0].get("format") in {"pth", "pt", "bin"}:
        from app.hub_avatar_candidates import resolve_profile as avatar_profile
        from app.runner_client import RunnerError, RunnerUnavailable

        try:
            report["avatar_profile"] = await avatar_profile(report, check)
        except (ValueError, httpx.HTTPError, RunnerError, RunnerUnavailable) as exc:
            report["requirements_error"] = str(exc)[:300]
        return
    if any(file.get("format") == "onnx" for file in report["files"]):
        from app.hub_embedding_candidates import resolve_profile as embedding_profile

        encoder_only = not any(file.get("format") in {"gguf", "safetensors"} for file in report["files"])
        try:
            report["embedding_profile"] = await embedding_profile(report, check)
        except (ValueError, httpx.HTTPError) as exc:
            if encoder_only:
                report["requirements_error"] = str(exc)[:300]
        if encoder_only:
            return
    if len(report["files"]) == 1 and any(
        file.get("format") == "safetensors" and file.get("identity_available") for file in report["files"]
    ):
        from app.hub_native_profiles import resolve_profile as native_profile
        from app.runner_client import RunnerError, RunnerUnavailable

        try:
            key, profile = await native_profile(report, check)
            report[key] = profile
        except (ValueError, httpx.HTTPError, RunnerError, RunnerUnavailable) as exc:
            report["requirements_error"] = str(exc)[:300]
        return
    if (
        "architecture_hint" in report
        and "base_models" in report
        and report.get("pipeline_hint") in {"text-to-image", "image-to-image"}
        and any(f.get("format") == "gguf" and f.get("identity_available") for f in report["files"])
    ):
        from app.hub_image_candidates import resolve_profile as image_profile
        from app.runner_client import RunnerError, RunnerUnavailable

        try:
            report["image_profile"] = await image_profile(report, check)
        except (ValueError, httpx.HTTPError, RunnerError, RunnerUnavailable) as exc:
            report["requirements_error"] = str(exc)[:300]
        return
    if (
        "architecture_hint" not in report
        or "base_models" not in report
        or report.get("architecture_hint") not in {None, "", "llama", "qwen2", "qwen3", "qwen35"}
        or report.get("pipeline_hint", "") not in {"", "text-generation"}
        or not any(f.get("format") == "gguf" and f.get("identity_available") for f in report["files"])
    ):
        return
    try:
        profile = await resolve_profile(report, check)
    except (ValueError, httpx.HTTPError) as exc:
        # Keep the source/file review usable if its configuration is unavailable.
        # Claim loss, Stop and outer timeouts are not swallowed here.
        report["requirements_error"] = str(exc)[:300]
    else:
        report["language_profile"] = profile.model_dump(mode="json")


def assess_variant(file, report, hardware, storage, *, context_target=32768):
    from app.hub_model_parts import for_file, looks_split

    existing = assess_file(file, hardware, storage, bundle=for_file(report, file))
    if file.get("bundle_id") or looks_split(file.get("filename", "")):
        from app.hub_split_candidates import INSTALLATION_QUALIFIED
        from app.hub_split_candidates import candidate_from_profile as split_candidate

        if INSTALLATION_QUALIFIED and report.get("language_profile"):
            try:
                entry = split_candidate(
                    report, file["filename"], report["language_profile"], context_ceiling=context_target
                )
                return assess_file(file, hardware, storage, candidates=(entry,))
            except ValueError as exc:
                existing["reason"] = str(exc)[:300]
        return existing
    if report.get("avatar_profile") and file.get("format") in {"pth", "pt", "bin"}:
        from app.hub_avatar_candidates import candidate_from_profile as avatar_candidate

        try:
            return assess_file(
                file, hardware, storage, candidates=(avatar_candidate(report, file["filename"]),)
            )
        except ValueError as exc:
            existing["reason"] = str(exc)[:300]
            return existing
    if report.get("embedding_profile") and file.get("format") == "onnx":
        from app.hub_embedding_candidates import candidate_from_profile as embedding_candidate

        try:
            return assess_file(
                file, hardware, storage, candidates=(embedding_candidate(report, file["filename"]),)
            )
        except ValueError as exc:
            existing["reason"] = str(exc)[:300]
            return existing
    from app.hub_native_profiles import adapters

    for key, adapter in adapters():
        if not report.get(key):
            continue
        try:
            return assess_file(
                file,
                hardware,
                storage,
                candidates=(adapter.candidate_from_profile(report, file["filename"]),),
            )
        except ValueError as exc:
            existing["reason"] = str(exc)[:300]
            return existing
    if report.get("image_profile"):
        from app.hub_image_candidates import candidate_from_profile as image_candidate

        try:
            return assess_file(
                file, hardware, storage, candidates=(image_candidate(report, file["filename"]),)
            )
        except ValueError as exc:
            existing["reason"] = str(exc)[:300]
            return existing
    if existing["profiles"] or not report.get("language_profile"):
        return existing
    try:
        entry = candidate_from_profile(
            report, file["filename"], report["language_profile"], context_ceiling=context_target
        )
    except ValueError as exc:
        existing["reason"] = str(exc)[:300]
        return existing
    return assess_file(file, hardware, storage, candidates=(entry,))


def rank_variants(report, *, context_target=32768):
    """Prefer useful context, fewer GPUs and an explicit quantization preference.

    Busy devices remain a capacity estimate; never stop/evict a process to improve
    this ranking. Unknown storage/geometry never earns the recommended badge.
    """
    scored = []
    for file in report["files"]:
        assessment = file["assessment"]
        profiles = [
            p
            for p in assessment["profiles"]
            if p["fit"] == "estimated_fit"
            and (p["recommendation"].get("gpus") or p["recommendation"].get("execution_device") == "cpu")
        ]
        best = max(
            profiles,
            key=lambda p: (
                int((p["recommendation"].get("context_size") or 0) >= context_target),
                -len(p["recommendation"]["gpus"]),
                p["recommendation"].get("context_size") or 0,
            ),
            default=None,
        )
        context = (best["recommendation"].get("context_size") or 0) if best else 0
        gpus = best["recommendation"]["gpus"] if best else []
        disk_fits = assessment["disk"]["status"] == "file_fits"
        usable = bool(best and disk_fits and assessment.get("runtime_status") != "runtime_unavailable")
        image = any(
            p.get("capability") in {"image", "video", "speech", "music", "avatar", "embedding"}
            for p in assessment["profiles"]
        )
        meets_context = bool(best and (image or context >= context_target))
        quant = best.get("quantization", "") if best else ""
        precision_known = quant in BALANCED and not quant.startswith(("Q2", "Q3", "IQ2", "IQ3"))
        # All scores are local to this immutable repository observation.
        score = (
            int(usable and meets_context and precision_known),
            int(usable and meets_context),
            int(usable),
            -len(gpus) if best else -100,
            BALANCED.get(quant, 0),
            -(assessment["disk"].get("model_bundle_bytes") or file.get("size_bytes") or 2**60),
        )
        assessment["variant_advice"] = {
            "policy": POLICY,
            "recommended": False,
            "context_target": None if image else context_target,
            "meets_context_target": None if image else bool(meets_context),
            "precision_tradeoff": bool(best and quant.startswith(("Q2", "Q3", "IQ2", "IQ3"))),
            "rank": 0,
            "reason": "CPU memory encoder · 384 dimensions · GPUs stay free"
            if best and best.get("capability") == "embedding"
            else "Estimated avatar, one 12-GiB GPU, 24-GiB RAM and explicit CPU offload"
            if best and best.get("capability") == "avatar"
            else "Estimated music, one 12-GiB GPU, 24-GiB RAM and explicit CPU offload"
            if best and best.get("capability") == "music"
            else "Estimated Polish speech, one 6-GiB GPU and fixed F32 profile"
            if best and best.get("capability") == "speech"
            else "Estimated 1280×704 video, one GPU and explicit CPU offload"
            if best and best.get("capability") == "video"
            else f"Estimated images up to {best['recommendation']['maximum_side']} px per side on {len(gpus)} GPUs"
            if image and best
            else f"Estimated {context:,}-token context on {len(gpus)} GPU(s)"
            if best
            else assessment["reason"],
        }
        scored.append((score, file, bool(usable and meets_context and precision_known)))
    scored.sort(key=lambda row: (row[0], row[1]["filename"]), reverse=True)
    recommended = next((file for _, file, eligible in scored if eligible), None)
    ranks = {}
    recommended_group = (recommended.get("bundle_id") or recommended["filename"]) if recommended else None
    for _, file, _ in scored:
        group = file.get("bundle_id") or file["filename"]
        ranks.setdefault(group, len(ranks) + 1)
        file["assessment"]["variant_advice"]["rank"] = ranks[group]
        file["assessment"]["variant_advice"]["recommended"] = group == recommended_group
    report["files"] = [file for _, file, _ in scored]
    report["recommendation_policy"] = POLICY
    report["context_target"] = context_target
