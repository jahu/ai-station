"""Private immutable observations shared by source planning and bounded comparisons."""

from fastapi import HTTPException

from app.model_setup import fingerprint
from app.models import Run


def verify(report):
    if not isinstance(report, dict):
        raise HTTPException(409, "The source observation is unavailable; inspect it again")
    actual = fingerprint({key: value for key, value in report.items() if key != "observation_sha256"})
    if actual != report.get("observation_sha256"):
        raise HTTPException(409, "The source observation changed; inspect and review it again")
    return report


def completed(session, identity):
    run = session.get(Run, str(identity))
    if run is None or run.executor_type != "model_hub_inspect" or run.status != "succeeded":
        raise HTTPException(404, "Completed model-source inspection not found")
    return verify(run.metadata_json.get("source_inspection"))


def search(session, identity, expected):
    report = completed(session, identity)
    if report.get("kind") != "search" or report.get("observation_sha256") != expected:
        raise HTTPException(409, "Choose an unchanged completed model search")
    return report


def source(session, identity, expected):
    report = completed(session, identity)
    if report.get("kind") == "comparison":
        matches = [
            item["observation"]
            for item in report.get("items", [])
            if isinstance(item.get("observation"), dict)
            and item["observation"].get("observation_sha256") == expected
        ]
        if len(matches) != 1:
            raise HTTPException(409, "Choose a completed source observation from this comparison")
        report = verify(matches[0])
    if (
        report.get("kind") in {"search", "install_plan", "comparison"}
        or report.get("observation_sha256") != expected
    ):
        raise HTTPException(409, "Choose an unchanged completed repository or file inspection")
    return report
