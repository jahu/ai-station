# Create a recurring agent from a selected analysis

Expose the deployed analysis-to-agent workflow directly beside a completed
conversation data result. A focused dialog previews the selected original task,
explains retained live/captured inputs and asks for scheduling instructions. The
operator chooses Prepare draft; the existing conversation receives its disabled
Agent Factory result for review/activation. Do not overwrite unsent composer text.

Add an optional typed `analysis_agent_source_run_id` on the conversation message.
It is accepted only with a current explicit Work/agent.create instruction. Resolve
that exact visible successful root inside the same conversation, including older
results; a missing/changed/foreign source fails without choosing a newer result.
Reuse existing capture/worker verification and receipt replay. Absent values must
be omitted from receipt fingerprints to preserve historical idempotency.

Offer the action only for local-provider general conversations. Archived, busy or
project-linked conversations cannot start it. Explicit user submission creates a
normal Work turn, without changing the saved mode or model. A network retry must
reuse its receipt ID; closing while a submission is pending must be prevented.
The modal is keyboard accessible and fits desktop/mobile, with clear source and
schedule labels. No new execution boundary, permissions, schema or native change.

Verify two analyses in the same conversation select the clicked older result;
foreign/stale/mixed/wrong-mode scopes fail; receipt replay creates one draft;
legacy fingerprints stay unchanged. Verify result action/dialog/cancel/failure
retry and preserved unsent text, then full required gates and compiled desktop/
mobile flow using isolated storage and actual native offline Python.

## Qualification

Source `feeb82c` passed 31 focused analysis-agent contracts and 37 focused UI
contracts, including prior Chat/data cases. The exact compiled image passed
1440/390-pixel browser flows with two completed analyses per conversation: the
clicked older result was retained, Cancel submitted nothing, and preparing the
draft preserved unsent composer text and the saved Chat mode. Explicit review and
enable led to actual scheduler ticks at forced due instants, fresh private agent
workspaces and fresh reviewed public-source captures. Six actual native offline
Python jobs completed. Inference/catalog/public HTTP responses were injected;
no GPU, production-record or physical-phone testing is claimed.

Full normal Python/Runner and frontend gates and final release review are tracked
under `data/acceptance/analysis-agent-action-20261024`; consult its final gate
reports and post-deployment qualification before treating PR #414 as live.

A separate real-model smoke used the already-ready owned llama.cpp instance
without reloading or changing its 46,080-token preset/container. One actual local
inference accepted a Polish daily-at-09:00 instruction, produced cron `0 9 * * *`
in `Europe/Warsaw`, and saved a disabled definition retaining the exact original
files and goal. Its original analysis/Python execution were synthetic and all
records were isolated. This qualifies actual drafting separately from the compiled
browser/native-Python cases. Evidence: `real-local-draft-result.json`.

The initial complete CPU run exposed two outdated historical-receipt fixtures:
new-schema model_dump included the new optional field while their simulated old
schema did not remove it. Both fixture snapshots now omit that field. All 36
contracts in the two files passed; the complete affected shard is repeated, with
original failures retained. Production code and assertions were not weakened.
