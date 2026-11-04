"""Preserve explicit user cadence and canonicalize new, reviewable schedules."""


def schedule_values(values: dict, *, instruction: str = "") -> dict:
    # Explicit user cadence is authoritative, even when the model omits it or
    # returns the schema's default manual trigger. Existing definitions are not
    # rewritten. Unsupported natural language still uses the reviewed proposal.
    if instruction:
        from app.factory import instruction_schedule

        trigger, cron, interval, once = instruction_schedule(instruction.casefold(), instruction)
        if trigger != "manual":
            if trigger == "interval" and interval % 60 == 0:
                minutes = interval // 60
                if minutes <= 60 and 60 % minutes == 0:
                    trigger, cron, interval = (
                        "cron",
                        f"*/{minutes} * * * *" if minutes < 60 else "0 * * * *",
                        None,
                    )
                elif minutes % 60 == 0 and minutes <= 1440 and 24 % (minutes // 60) == 0:
                    hours = minutes // 60
                    trigger, cron, interval = (
                        "cron",
                        f"0 */{hours} * * *" if hours < 24 else "0 0 * * *",
                        None,
                    )
            values = {
                **values,
                "trigger": trigger,
                "cron_expr": cron,
                "interval_seconds": interval,
                "run_at": once,
            }

    trigger = values.get("trigger", "manual")
    return {
        **values,
        "cron_expr": values.get("cron_expr", "") if trigger == "cron" else "",
        "interval_seconds": values.get("interval_seconds") if trigger == "interval" else None,
        "run_at": values.get("run_at") if trigger == "datetime" else None,
    }
