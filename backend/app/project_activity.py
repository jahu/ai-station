"""Classify immutable artifact inspection without hiding project provenance."""

from app.models import Run

READ_ONLY_VIEWERS = ("site_preview", "site_preview_action", "site_preview_close")


def project_write_condition():
    return Run.executor_type.not_in(READ_ONLY_VIEWERS)
