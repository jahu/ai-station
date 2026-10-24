"""Turn a natural-language request into a disabled agent draft."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.http_fetch import prompt_public_urls
from app.models import Agent
from app.schedule_time import instruction_timezone
from app.skills import SkillError, list_skills

_TOOL_CALLING = (
    "tool calling",
    "call tools",
    "function calling",
    "wywołuj narzędzia",
    "wywoluj narzedzia",
)
_APPROVAL = (
    "require approval",
    "ask before each run",
    "wymagaj zatwierdzenia",
    "zatwierdź przed każdym",
    "zatwierdz przed kazdym",
)
_GATED = (
    "gated",
    "inspect tools first",
    "wait after tools",
    "bramkowany",
    "zatwierdź raport po",
    "zatwierdz raport po",
)
_RETRY = ("manual retry", "retry manually", "allow retry", "ręcznie ponów", "recznie ponow", "ponów ręcznie")
_REMEMBER_REPORTS = (
    "remember reports",
    "retain reports",
    "save reports",
    "zapamiętuj raporty",
    "zapamietuj raporty",
)
_REMEMBER_WORKFLOW = (
    "remember workflow",
    "remember observations",
    "remember steps",
    "pamiętaj obserwacje",
    "pamietaj obserwacje",
    "pamiętaj kroki",
    "pamietaj kroki",
)
_DOW = (
    ("sunday", "0"),
    ("monday", "1"),
    ("tuesday", "2"),
    ("wednesday", "3"),
    ("thursday", "4"),
    ("friday", "5"),
    ("saturday", "6"),
    ("niedziel", "0"),
    ("poniedział", "1"),
    ("poniedzial", "1"),
    ("wtorek", "2"),
    ("środ", "3"),
    ("srod", "3"),
    ("czwartek", "4"),
    ("piątek", "5"),
    ("piatek", "5"),
    ("sobot", "6"),
)


def _mentioned_skills(text: str) -> list[str]:
    lowered = text.lower()
    try:
        catalog = list_skills()
    except SkillError:
        return []
    found = []
    for skill in catalog:
        if re.search(rf"(?<![a-z0-9-]){re.escape(skill.id)}(?![a-z0-9-])", lowered) or (
            skill.name.lower() in lowered
        ):
            found.append(skill.id)
    return found[:4]


def _has(lowered: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in lowered for phrase in phrases)


def _clock(lowered: str) -> tuple[int, int] | None:
    match = re.search(r"\b(?:at|o)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lowered)
    if not match:
        return None
    if (
        match.group(2) is None
        and match.group(3) is None
        and not any(
            marker in lowered
            for marker in ("every ", "daily", "codziennie", "co rano", "co wiecz", "dni robocze")
        )
    ):
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if match.group(3):
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if match.group(3) == "pm" else 0)
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def _schedule(lowered: str, original: str) -> tuple[str, str, int | None, datetime | None]:
    once = re.search(
        r"once at (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2}))",
        original,
        re.IGNORECASE,
    )
    if once:
        stamp = datetime.fromisoformat(once.group(1).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return "manual", "", None, None
        return "datetime", "", None, stamp.astimezone(timezone.utc)
    for factor, units in (
        (3600, r"hours?|godzin[ęey]?"),
        (60, r"minutes?|minut[ęey]?"),
        (1, r"seconds?|sekund[ęey]?"),
    ):
        interval = re.search(rf"\b(?:every|co)\s+([+-]?\d+(?:[.,]\d+)?)\s+(?:{units})\b", lowered)
        if interval:
            digits = interval.group(1)
            # The API accepts at most a year; bound numeric conversion as well.
            if len(digits) <= 8 and digits.isdecimal():
                seconds = int(digits) * factor
                if 60 <= seconds <= 31536000:
                    return "interval", "", seconds, None
            return "manual", "", None, None
    if re.search(r"\b(?:every minute|co minut[ęe])\b", lowered):
        return "interval", "", 60, None
    clock = _clock(lowered)
    hour, minute = clock if clock else (9, 0)
    if "every morning" in lowered or "co rano" in lowered:
        if clock is None:
            hour, minute = 8, 0
        return "cron", f"{minute} {hour} * * *", None, None
    if "every evening" in lowered or "co wieczór" in lowered or "co wieczor" in lowered:
        if clock is None:
            hour, minute = 20, 0
        return "cron", f"{minute} {hour} * * *", None, None
    if "every hour" in lowered or "co godzinę" in lowered or "co godzine" in lowered:
        return "interval", "", 3600, None
    if any(word in lowered for word in ("weekdays", "weekday", "dni robocze", "w dni robocze")):
        return "cron", f"{minute} {hour} * * 1-5", None, None
    for name, value in _DOW:
        if f"every {name}" in lowered or f"w {name}" in lowered:
            return "cron", f"{minute} {hour} * * {value}", None, None
    if any(word in lowered for word in ("every week", "weekly", "co tydzień", "co tydzien")):
        return "cron", f"{minute} {hour} * * 1", None, None
    if any(word in lowered for word in ("every day", "daily", "codziennie")) or clock is not None:
        return "cron", f"{minute} {hour} * * *", None, None
    return "manual", "", None, None


def _search_query(text: str) -> str:
    match = re.search(
        r'(?:public (?:search )?query|search for|szukaj)\s+"([^"]{1,500})"',
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def website_build_goal(lowered):
    # Bind the creation verb to the site, rather than to an agent that only reads it.
    verb = r"(?:build\w*|creat\w*|recreat\w*|clon\w*|stw[oó]rz\w*|utw[oó]rz\w*|tw[oó]rz\w*|buduj\w*|zbuduj\w*|odtw[oó]rz\w*|przebuduj\w*|tworzy\w*)"
    modifier = r"(?:a|an|the|me|mi|new|modern|responsive|static|complete|small|news|personal|business|version|of|this|now[aą]|nowej|wersj[eę]|tej|lepsz[aą])"
    return bool(
        re.search(rf"\b{verb}\s+(?:{modifier}\s+){{0,5}}(?:website|web app|stron\w*|witryn\w*)\b", lowered)
    )


def draft_agent(text: str, *, model: str = "", schedule_timezone: str = "UTC") -> Agent:
    lowered = text.lower()
    trigger, cron_expr, interval, run_at = _schedule(lowered, text)
    name = text.strip().split(".")[0][:80] or "New agent"
    tools = []
    if "github" in lowered:
        tools.append("github_read")
    if any(word in lowered for word in ("gpu", "hardware", "workstation", "system", "stacji")):
        tools.append("system_snapshot")
    if _has(lowered, _REMEMBER_REPORTS):
        tools.append("remember_report")
    if _has(lowered, _REMEMBER_WORKFLOW):
        tools.append("remember_workflow")
    if any(word in lowered for word in ("memory", "remember", "pamię", "pamie")):
        tools.append("memory_search")
    search_query = _search_query(text)
    if (
        search_query
        or re.search(r"\bweb\b", lowered)
        and not website_build_goal(lowered)
        or any(
            word in lowered for word in ("search", "internet", "news", "szukaj", "wiadomości", "wiadomosci")
        )
    ):
        tools.append("web_search")
    fetch_urls = prompt_public_urls(text)
    if any(
        word in lowered
        for word in ("browse", "browser", "javascript", "przeglądaj", "przegladaj", "zrzut stron")
    ):
        tools.append("browser")
    elif fetch_urls or any(word in lowered for word in ("fetch", "pobierz stron")):
        tools.append("http_fetch")
    if re.search(
        r"\b(coding agent|write code|(?:build(?:s|ing)?|creat(?:e|es|ing)|recreat(?:e|es|ing)|clon(?:e|es|ing)) (?:a )?(?:website|web app)|implement features|agent koduj[aą]cy|pisz kod|(?:tw[oó]rz|buduj|tworzy[łl]|tworzy|buduje) stron[eęy])\b",
        lowered,
    ) or website_build_goal(lowered):
        wants_coding = True
    else:
        wants_coding = False
    if wants_coding and set(tools) <= {"web_search", "search_pages", "http_fetch"}:
        chosen = (
            "codex"
            if re.search(r"\bcodex\b", lowered)
            else "cursor"
            if re.search(r"\bcursor\b", lowered)
            else "local"
        )
        tools = ["coding_" + chosen] + (tools if chosen == "local" else [])
    if (
        not wants_coding
        and set(tools) <= {"web_search", "search_pages", "http_fetch"}
        and re.search(r"\b(excel|xlsx|csv|spreadsheet\w*|arkusz\w*|json)\b", lowered)
    ):
        tools = ["python_data", *tools]
    market = None
    stock_request = re.search(r"\b(?:stocks?|akcj\w*|giełd\w*|gield\w*)", lowered)
    stock_research = bool(
        not wants_coding
        and "python_data" not in tools
        and stock_request
        and re.search(r"(?:price|cen[ayę]|kurs)", lowered)
        and not re.search(r"\bfinnhub\b", lowered)
    )
    if stock_research:
        # An illustrative research goal does not select an account-based provider.
        # Keep explicit pages/queries for review; never disclose the entire goal
        # (which may contain private instructions or recipients) to a search engine.
        if not fetch_urls and "web_search" not in tools:
            tools.append("web_search")
    if (
        not wants_coding
        and "python_data" not in tools
        and not stock_research
        and (re.search(r"\b(?:bitcoin\w*|btc|ethereum|eth)\b", lowered) or stock_request)
        and re.search(r"(?:price|cen[ayę]|kurs)", lowered)
    ):
        from app.market_schema import MarketScope

        instruments = []
        currency = "EUR" if re.search(r"\b(?:eur|euro)\b", lowered) else "USD"
        if re.search(r"\b(?:bitcoin\w*|btc)\b", lowered):
            instruments.append("BTC-" + currency)
        if re.search(r"\b(?:ethereum|eth)\b", lowered):
            instruments.append("ETH-" + currency)
        threshold = re.search(r"(?<![\d.,])([0-9]{1,3}(?:[.,][0-9]{1,4})?)\s*%", lowered)
        value = threshold.group(1).replace(",", ".") if threshold else "5"
        provider = "coinbase_exchange"
        if stock_request:
            from app.stock_quotes import stock_symbol

            provider = "finnhub"
            instruments = []
            for symbol in re.findall(r"(?<![\w:])\$?([A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*)(?![\w:])", text):
                if symbol in {"AI", "USD", "EUR", "US", "UTC", "ETF", "API", "SMTP", "LLM"}:
                    continue
                try:
                    stock_symbol(symbol)
                except ValueError:
                    continue
                if symbol not in instruments and len(instruments) < 3:
                    instruments.append(symbol)
        try:
            market = MarketScope(
                provider=provider, instruments=instruments, threshold_percent=value
            ).model_dump(mode="json")
        except ValueError:
            market = MarketScope(provider=provider, instruments=instruments).model_dump(mode="json")
        tools = ["market_watch"]
        fetch_urls, search_query = [], ""
    notices = {
        "on_success": _has(lowered, ("notify on success", "powiadom o sukcesie")),
        "on_failure": _has(
            lowered,
            ("notify on failure", "alert on failure", "powiadom o błędzie", "powiadom o bledzie"),
        ),
        "on_approval": _has(
            lowered, ("notify when waiting", "notify on approval", "powiadom o zatwierdzeniu")
        ),
    }
    build_website = "coding_local" in tools and website_build_goal(lowered)
    agent = Agent(
        name=name,
        description=text.strip()[:500],
        goal=text.strip(),
        system_prompt=(
            "You are a persistent AI Station agent. Stay within the granted permissions. "
            "Prefer local information. Do not invent tool results. "
            "Use the goal supplied with each execution."
        ),
        market=market,
        data={"input_artifact_ids": [], "max_repairs": 1}
        if "python_data" in tools and set(tools) != {"python_data"}
        else None,
        model=""
        if tools in (["coding_codex"], ["coding_cursor"], ["market_watch"])
        else "auto"
        if "coding_local" in tools or "python_data" in tools
        else model,
        provider="local-openai-compatible",
        runtime="openai-compatible",
        execution_target="container",
        memory_scope="agent",
        maximum_runtime=1800 if build_website else 600,
        workspace_policy={"auto_install_dependencies": True, "auto_validate": True} if build_website else {},
        tools=tools,
        search_query=search_query,
        fetch_urls=fetch_urls,
        skills=[] if market else _mentioned_skills(text),
        trigger=trigger,
        cron_expr=cron_expr,
        schedule_timezone=instruction_timezone(text, schedule_timezone),
        interval_seconds=interval,
        run_at=run_at,
        permission_profile="agent_external_coding"
        if tools in (["coding_codex"], ["coding_cursor"])
        else "agent_local",
        enabled=False,
        require_approval=_has(lowered, _APPROVAL) or tools in (["coding_codex"], ["coding_cursor"]),
        workflow_mode="gated" if not market and _has(lowered, _GATED) else "sequential",
        tool_calling="bounded" if not market and _has(lowered, _TOOL_CALLING) else "none",
        output_expectation="A working website with passing checks, a static build and downloadable output."
        if build_website
        else "A source-linked research report with source dates when available. "
        "Distinguish public findings from verified live quotes; do not claim email delivery."
        if stock_research
        else "A short report the user can inspect in Runs.",
        notification_policy=notices,
        retry_policy={"mode": "manual" if _has(lowered, _RETRY) else "none"},
    )
    agent.next_run_at = None
    return agent
