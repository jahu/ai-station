"""Controller-owned output expectations; never extra tool or command authority."""

import re

STATIC_SITE = "static_site"


def website_output(goal):
    """Recognize explicit website construction in the reviewed agent goal."""
    create = re.search(
        r"\b(?:build|create|rebuild|redesign|zbud\w*|stw[oó]rz\w*|utw[oó]rz\w*|przebud\w*)\b", goal, re.I
    )
    website = re.search(
        r"\b(?:website|web\s+(?:site|page)|landing\s+page|html|stron\w*|witryn\w*)\b", goal, re.I
    )
    return STATIC_SITE if create and website else None


def validation_contract(session, run):
    from app.models import Run

    source = session.get(Run, run.parent_run_id) if run.parent_run_id else None
    expected = source.parameters.get("output_contract") if source else None
    actual = run.parameters.get("output_contract")
    if actual != expected or actual not in {None, STATIC_SITE}:
        raise ValueError("Validation output expectation does not match its coding source")
    return actual


def output_check(contract, files):
    if contract is None:
        return None
    if contract != STATIC_SITE:
        raise ValueError("Unsupported coding output expectation")
    present = "index.html" in (files or ())
    return {
        "source": "control_plane",
        "contract": STATIC_SITE,
        "required": "dist/index.html in the verified build archive",
        "succeeded": present,
        "error": ""
        if present
        else "The website build did not produce a nonempty dist/index.html. Fix the build output before preview or download.",
    }
