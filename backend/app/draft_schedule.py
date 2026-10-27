"""Canonicalize inactive fields only in new, reviewable model-authored drafts."""


def schedule_values(values: dict) -> dict:
    trigger = values.get("trigger", "manual")
    return {
        **values,
        "cron_expr": values.get("cron_expr", "") if trigger == "cron" else "",
        "interval_seconds": values.get("interval_seconds") if trigger == "interval" else None,
        "run_at": values.get("run_at") if trigger == "datetime" else None,
    }
