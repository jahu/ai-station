# Agent schedules in local time

Persist an operator-selected IANA `schedule_timezone` on Agent definitions. Existing
records and old API clients default to UTC; migration must not alter `next_run_at`,
cron strings, enabled flags, history or permissions. Store due instants in UTC.
Daily/calendar cron uses the selected zone; interval schedules remain elapsed-time
intervals and one-shot timestamps retain their existing explicit-offset contract.

Calendar semantics: enumerate cron wall-clock minutes, then resolve the selected
zone to UTC. Skip nonexistent wall times on forward clock changes. On a backward
change, use the first occurrence only, even when computing the next occurrence
from inside the repeated hour. Require a strictly future UTC instant. Bound both
cron search (five years) and skipped wall times; malformed/impossible rules fail
validation. Existing atomic scheduler claims, no-overlap, Tasks, Runs, Stop and
recovery remain unchanged.

Agents and the inline conversation editor share daily-time/custom-cron controls
and a timezone selector. Daily at 09:00 is the happy path; arbitrary five-field
cron stays available as an advanced choice. Show the saved zone in summaries.
New drafts use the browser's zone, passed as current operator input; local-model
proposals cannot change it. Existing drafts/definitions retain their saved zone.
Propagate the current browser zone through Work agent creation as well. Keep
one-shot UTC labels explicit rather than silently interpreting their existing
inputs in a new zone.

Use stdlib ZoneInfo plus the small first-party tzdata dependency for portable
fallback data. Valid choices come from the packaged IANA list. Do not change OS
clock, host timezone, other agents, NVIDIA or external services.

Qualification: migration/backfill and schema parity; UTC/positive/negative offsets;
spring gaps, autumn folds, half-hour changes and an already-repeated local hour;
future/search bounds; API validation/edit/duplicate/restart; concurrent scheduler
claim, no overlap and definition snapshot; both editors, new/old draft provenance,
daily/custom controls, keyboard/mobile display and reload. Run the complete local
backend/Runner and frontend gates, Docker/Compose and a short normal-worker fake-
executor schedule acceptance. No expensive inference is needed to prove timing.
Back up the live SQLite database before migrating to 0033; verify existing IDs,
credentials and pre-existing UTC schedules/next instants afterward.

Sources: [Python 3.12 ZoneInfo](https://docs.python.org/3.12/library/zoneinfo.html),
[croniter](https://github.com/pallets-eco/croniter#about-dst),
[first-party tzdata](https://pypi.org/project/tzdata/).
