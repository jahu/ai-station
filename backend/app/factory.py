"""Turn a natural-language request into a disabled agent draft."""

from __future__ import annotations

from app.models import Agent
from app.schedule import compute_next


def draft_agent(text: str, *, model: str = "") -> Agent:
    lowered = text.lower()
    trigger = "manual"
    cron_expr = ""
    interval = None
    if "every morning" in lowered:
        trigger = "cron"
        cron_expr = "0 8 * * *"
    elif "every hour" in lowered:
        trigger = "interval"
        interval = 3600
    elif "every day" in lowered or "daily" in lowered:
        trigger = "cron"
        cron_expr = "0 9 * * *"
    name = text.strip().split(".")[0][:80] or "New agent"
    tools = ["read_file"]
    if any(word in lowered for word in ("search", "web", "internet", "news")):
        tools.append("http_fetch")
    agent = Agent(
        name=name,
        description=text.strip()[:500],
        goal=text.strip(),
        system_prompt=(
            "You are a persistent AI Station agent. Stay within the granted permissions. "
            "Prefer local information. Do not invent tool results. "
            f"The user's goal is:\n{text.strip()}"
        ),
        model=model,
        tools=tools,
        skills=[],
        trigger=trigger,
        cron_expr=cron_expr,
        interval_seconds=interval,
        permission_profile="agent_minimal",
        enabled=False,
        output_expectation="A short report the user can inspect in Runs.",
        notification_policy={"surface": "runs"},
        retry_policy={"auto": False},
    )
    if trigger != "manual":
        agent.next_run_at = compute_next(agent)
    return agent
