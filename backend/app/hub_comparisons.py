"""Compare three immutable source observations, never weights, inference or quality."""

import asyncio
import json

import httpx

from app.db import utcnow
from app.events import append_event
from app.hub_observations import search as search_observation
from app.hub_sources import parse_source
from app.model_setup import fingerprint
from app.model_variant_advice import assess_variant, enrich_source, rank_variants
from app.runner_client import RunnerError, RunnerUnavailable

LIMIT = 3
MAX_FILES = 64
MAX_OBSERVATION_BYTES = 512 * 1024


def suitability(observation, installed, context_target):
    choices = []
    gated = bool(observation.get("gated"))
    for file in observation["files"]:
        assessment = file["assessment"]
        supported = assessment["runtime_status"] not in {"runtime_unavailable", "needs_compatible_recipe"}
        fit = (
            not gated
            and supported
            and assessment["hardware_status"] == "estimated_fit"
            and assessment["disk"]["status"] == "file_fits"
        )
        advice = assessment.get("variant_advice") or {}
        context = advice.get("meets_context_target")
        meets = fit and context is not False
        present = assessment["disk"].get("model_weights_available", file.get("sha256") in installed)
        cost = assessment["disk"].get(
            "additional_bytes_upper_bound",
            assessment["disk"].get("install_bytes_upper_bound", file.get("size_bytes")),
        )
        cost = cost if type(cost) is int and cost >= 0 else 2**63
        # Installed bytes do not excuse insufficient context or an unsupported adapter.
        score = (
            int(meets),
            int(fit),
            int(supported),
            int(present),
            int(advice.get("recommended", False)),
            -cost,
        )
        status = (
            "access_required"
            if gated
            else "fits"
            if meets
            else "limited_context"
            if fit
            else "unsupported"
            if not supported
            else "unknown"
            if assessment["hardware_status"] == "unknown" or assessment["disk"]["status"] == "unknown"
            else "insufficient_storage"
            if assessment["disk"]["status"] == "insufficient"
            else "does_not_fit"
        )
        summary = (
            "Publisher access is required before these weights can be downloaded."
            if gated
            else "Not enough application storage for this installation."
            if status == "insufficient_storage"
            else "Application storage could not be confirmed."
            if assessment["disk"]["status"] == "unknown"
            else advice.get("reason")
            if fit
            else next((p["recommendation"]["reason"] for p in assessment["profiles"]), assessment["reason"])
        )
        choices.append(
            (
                score,
                {
                    "suitability": status,
                    "filename": file["filename"],
                    "installed_object": present,
                    "download_bytes_estimate": assessment["disk"].get(
                        "model_download_bytes_estimate", file.get("size_bytes")
                    ),
                    "additional_installation_bytes_upper_bound": None if cost == 2**63 else cost,
                    "summary": summary or assessment["reason"],
                    "context_target": context_target if context is not None else None,
                    "busy_now": any(p.get("occupancy") == "in_use" for p in assessment["profiles"]),
                },
            )
        )
    return max(
        choices,
        key=lambda pair: pair[0],
        default=(
            (0, 0, 0, 0, 0, -(2**63)),
            {
                "suitability": "unsupported",
                "summary": "No inspectable compatible weights; choose a specific source file.",
            },
        ),
    )


async def inspect(session, run, check, inspect_source, hardware, storage):
    request = run.parameters["comparison"]
    search = search_observation(session, request["search_run_id"], request["observation_sha256"])
    rows = search.get("items", [])[:LIMIT]
    context = request["context_target"]
    session.commit()
    results = []
    for index, row in enumerate(rows):
        check()
        source = parse_source(row["source_url"])
        if source.repository != row["repository"] or source.filename:
            raise ValueError("The saved search does not contain a matching repository")
        append_event(
            session,
            run.id,
            "model.comparison.progress",
            {
                "repository": source.repository,
                "completed": index,
                "total": len(rows),
                "metadata_only": True,
            },
        )
        session.commit()
        result = {**row, "suitability": "unavailable", "compatibility": "unavailable"}
        try:
            async with asyncio.timeout(20):
                observation = await inspect_source(source, check)
                if len(observation["files"]) > MAX_FILES:
                    raise ValueError(
                        "Too many variants for a bounded comparison; inspect a specific model file"
                    )
                await enrich_source(observation, check)
            for file in observation["files"]:
                check()
                file["assessment"] = assess_variant(
                    file, observation, hardware, storage, context_target=context
                )
            from app.model_cache_advice import apply as apply_cache_advice

            installed = apply_cache_advice(session, observation, check)
            rank_variants(observation, context_target=context)
            observation.update(
                observed_at=utcnow().isoformat(),
                hardware_observed=not hardware.get("storage_unavailable", False),
                no_weights_downloaded=True,
            )
            if len(json.dumps(observation).encode()) > MAX_OBSERVATION_BYTES:
                raise ValueError("Source metadata exceeds comparison limits; inspect it separately")
            observation["observation_sha256"] = fingerprint(observation)
            score, summary = suitability(observation, installed, context)
            result.update(**summary, observation=observation, compatibility="inspected")
        except (ValueError, httpx.HTTPError, RunnerError, RunnerUnavailable, TimeoutError) as exc:
            check()  # Claim loss, Stop and revoked authority never become a source warning.
            result["summary"] = (
                str(exc)[:300] or "Source metadata timed out; inspect this repository separately"
            )
            score = (-1, 0, 0, 0, 0, -(2**63))
        results.append((score, result))
    check()
    results.sort(key=lambda pair: pair[0], reverse=True)
    return {
        "kind": "comparison",
        "query": search["query"],
        "items": [item for _, item in results],
        "files": [],
        "context_target": context,
        "metadata_only": True,
        "hardware_observed": not hardware.get("storage_unavailable", False),
        "search_run_id": request["search_run_id"],
        "limit": LIMIT,
        "note": "Ranked by supported workload fit, context, existing objects and estimated transfer cost. Not a quality or speed benchmark.",
    }
