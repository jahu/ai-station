"""Turn a natural-language request into a disabled agent draft."""

from __future__ import annotations

from app.http_fetch import prompt_public_urls
from app.models import Agent


def draft_agent(text: str, *, model: str = "") -> Agent:
    lowered = text.lower()
    trigger = "manual"
    cron_expr = ""
    interval = None
    if "every morning" in lowered or "co rano" in lowered:
        trigger = "cron"
        cron_expr = "0 8 * * *"
    elif "every hour" in lowered or "co godzinę" in lowered:
        trigger = "interval"
        interval = 3600
    elif "every day" in lowered or "daily" in lowered or "codziennie" in lowered:
        trigger = "cron"
        cron_expr = "0 9 * * *"
    name = text.strip().split(".")[0][:80] or "New agent"
    tools = []
    if any(word in lowered for word in ("gpu", "hardware", "workstation", "system", "stacji")):
        tools.append("system_snapshot")
    if any(word in lowered for word in ("memory", "remember", "pamię")):
        tools.append("memory_search")
    if any(word in lowered for word in ("search", "web", "internet", "news", "szukaj", "wiadomości")):
        tools.append("web_search")
    fetch_urls = prompt_public_urls(text)
    if fetch_urls or any(word in lowered for word in ("fetch", "pobierz stron")):
        tools.append("http_fetch")
    agent = Agent(
        name=name,
        description=text.strip()[:500],
        goal=text.strip(),
        system_prompt=(
            "You are a persistent AI Station agent. Stay within the granted permissions. "
            "Prefer local information. Do not invent tool results. "
            "Use the goal supplied with each execution."
        ),
        model=model,
        provider="local-openai-compatible",
        runtime="openai-compatible",
        execution_target="container",
        memory_scope="agent",
        maximum_runtime=600,
        tools=tools,
        fetch_urls=fetch_urls,
        skills=[],
        trigger=trigger,
        cron_expr=cron_expr,
        interval_seconds=interval,
        permission_profile="agent_local",
        enabled=False,
        output_expectation="A short report the user can inspect in Runs.",
        notification_policy={"surface": "runs"},
        retry_policy={"auto": False},
    )
    agent.next_run_at = None
    return agent
