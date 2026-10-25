# Internal acceptance and operator test coverage

Review date: 2026-10-25. This maps all 157 stable operator cases in catalog v10
to the current source and recorded acceptance. It does not fill operator results
or declare platform completion. The current release and exact local qualification
are in [the release audit](../plans/platform-acceptance-audit.md).

For the table, **regression** means the source-bound normal Python/Runner
qualification identified in the release audit and latest implementation plan;
frontend qualification retains the identical PR #444 frontend tree (844 tests
and all gates).
Fixtures and a module name are not evidence of real inference. Historical real
receipts remain bound to their original release, model and parameters. Receipt
paths below are relative to ignored `data/acceptance/`; retained files, not this
table alone, are the evidence. **External setup** is an open release gate.

| Stable cases | Source / regression boundary | Acceptance and exact outstanding scope |
| --- | --- | --- |
| START-001–005 | Startup supervisor, migrations, recovery and backup services; `scripts/start.sh`, `backend/tests/test_runs.py` | Current owned deployment, image/SQL/SSE smoke, backup and original-data preservation in `unified-natural-agent-intent-20261025/`. Launch does not prove arbitrary host bootstrap. |
| ACCESS-001–007 | `test_operator_auth.py`, `test_private_ui.py`; native `test_tailnet*.py` | LAN/password and actual private daemon lifecycle qualified; current daemon is installed 1.104.2, `NeedsLogin`, `serving: false`. Actual account enrollment/HTTPS/phone outside LAN remains **external setup**. |
| CHAT-001–011 | `test_chat.py`, `test_chat_turns.py`, `test_chat_providers.py`, `test_chat_reasoning.py`, `test_chat_cookie_concurrency.py` | Current compiled direct reply/stream/Stop/history flows plus earlier real llama.cpp, 27B context and Vision receipts. Physical-device rendering and operator model preference remain operator QA. |
| WORK-001–007; UNIFIED-001–006 | `test_chat_execution_mode.py`, `test_agent_request_intent.py`, `test_conversation_data.py`, `test_conversation_agent_control.py` | `unified-assistant-chat-20261025/` and `unified-natural-agent-intent-20261025/` prove desktop/phone viewport, direct reply/media review/retry/Stop, polite disabled drafts, default Web isolation and old-history/draft preservation. Inference is injected in those compiled checks. Real executors have separate receipts below. |
| WEB-001–007 | `test_web_search.py`, `test_chat_rendered_pages.py`, `test_work_web_routing.py` | Real search/follow-up: `chat-contextual-search-20261015/real-smoke-result.json`; real direct page reading: `chat-direct-page-reading-20261022/production-smoke-result.json`. Public-source relevance is not guaranteed for every future query. Native/private service URL rejection is regression-qualified. |
| IMAGE-001–010 | `test_images.py`, `test_krea_images.py`; native `test_photo.py`, `test_photo_model_selection.py` | Six original real photo operations in `docs/mvp-acceptance.md`; current Krea four modes/Stop GPU-only in `krea2-lustify-20261025/milestone-complete.json`. Retain original scripts; unqualified FP8 weights are not enabled. |
| VIDEO-001–004 | `test_video.py`, `test_video_storyboard.py`, `test_video_memory_profile.py`; native `test_wan_motion.py` | Real short standard translation video and historical 60-second segmented draft exist. Scope and quality differ: see profiles below. Do not present the 60-second four-step draft as standard-quality long-film acceptance. |
| AUDIO-001–005 | `test_audio.py`, `test_music_model_setup.py`, native managed processes | Actual speech/music/transcription receipts in the product ledger; actual ten-second ACE music in `agent-media-generation-20261023/real-agent-media-result.json` and translator/music receipt. Voice-reference quality needs the appropriate supplied recording, not a synthetic tone. |
| AVATAR-001–004 | `test_avatars.py`, `test_avatar_budgets.py`, `test_avatar_memory_profile.py`; native `test_echo_motion.py` | Actual five-second bounded-memory and historical 30-second avatar, full decode and recorded joins/playback. General word-level lip-sync and all long profiles are **not qualified**. |
| AGENT-001–014 | `test_agent_drafts.py`, `test_agent_coding.py`, `test_agent_outcome.py`, `test_agent_media_drafts.py`, `test_agent_email_attachments.py` | Real website/data and image/music pipelines have separate receipts. `agent-video-release-20261025/` actually qualifies natural drafting, goal preparation, two GPU windows and a five-second film; PR #448 separately checks proposed and explicit runtimes with actual local inference and compiled Settings. The earlier `agent-long-media-output-20261023/production-agent-result.json` stays **false**. Longer-film quality has its own open gate. Mail attachments use actual private TLS SMTP with injected inference, not operator-inbox delivery. |
| SCHED-001–004 | `test_agents.py`, `test_schedule_timezones.py`, `test_agent_recurrence.py`, `test_agent_settings_schedule.py` | Durable atomic dispatch/timezones/restarts and deployed due-instant preservation. Do not alter existing schedules for QA; create/pause disposable definitions. |
| DATA-001–008 | `test_python_data_agents.py`, `test_required_data_exports.py`, `test_data_result_reference.py` | Corrected real Auto chain: `data-agent-input-contract-20261022/production-smoke-result.json`, total 150, source preserved. Real context/output chain: `file-creation-conversation-context-20261024/post-deployment-qualified.json`. The QA package ships input CSV, two-sheet XLSX, document and explicit invalid input. |
| MEM-001–009 | `test_memory_api.py` and managed embeddings lifecycle | `managed-memory-release-20261025/activation-result.json`: actual E5 INT8 CPU, 384 dimensions, all three existing entries indexed. Scoped/disabled/stale-vector retrieval and cancellation/reopen are separately tested. |
| MODEL-001–005 | `test_model_catalog.py`, `test_llama.py`; native `test_llama_runtime.py`, `test_model_verify.py` | `gguf-context-20261013/long-context-result.json` and actual website 131072-context profile. Model metadata/training context is not an admission or quality guarantee for every quantization/VRAM allocation. |
| LIB-001–011 | `test_artifact_purge.py`, artifacts API and compiled Library/inspector | `library-permanent-deletion-20261025/` and follow-up #440 cover bypass Trash, one/selected/all Trash, receipts, source tombstones and live refresh. Use disposable uploads; never empty an operator collection to satisfy a case. |
| RUN-001–005 | `test_runs.py`, `test_worker_slots.py`, `test_worker_database_busy.py`; native `test_processes.py` | Current complete suite plus exact image API/worker/SSE/persistence and three actual worker heartbeats. Lost leases remain inspectable rather than blindly replaying side effects. No claim of an arbitrary-duration stress benchmark. |
| CONNECT-001–004 | `test_connectors.py`, `test_github_connector.py`, `test_email_tls_sink.py`, `test_agent_report_email_delivery.py` | Named GET and existing authenticated GitHub reads; private TLS SMTP single submission/attachment hashes in `agent-data-email-attachments-20261024/real-cpu-tls-result.json`. Read-only live DB audit finds zero email connectors: actual external account/delivery is **external setup**, not a passed inbox test. |
| SYSTEM-001–003 | `test_dashboard.py`; native `test_telemetry.py`, typed diagnostics | Current native observation sees both real GPUs, available media and actual private Runner; compiled page/gate coverage separates System and Settings. A readiness GET starts no inference. |
| UX-001–004 | Compiled 1440px/390px flows and frontend tests | Final #444/#445 flows show no mode switch, overflow or JavaScript errors; keyboard/focus/empty/error component coverage remains in the full frontend suite. A phone viewport is not a physical-phone test. |
| PROJECT-001–004 | `test_projects.py`, `test_agent_workspace.py`, `test_agent_website_policy.py`; native `test_gitinspect.py` | Real `agent-website-real-20261022/result.json`: isolated Auto-loaded local build, preview and follow-up, original checkout retained. Advanced repository policies and bounded validation stay available without expanding standalone IDE scope. |
| DICT-001–007 | Composer dictation tests and native CPU transcription lifecycle | PR #441 actual CPU file transcription and compiled draft/caret/Stop/reload qualification. Physical microphone permission/recording and HTTPS phone microphone remain operator/device acceptance; no fabricated recording claim. |
| TRANS-001–013 | `test_media_translation.py`, `test_media_translation_text.py`, `test_media_translation_transport.py` | Actual translator→LUSTIFY same-seed comparison and translator→music/standard short Wan in `media-language-workflows-20261025/real-standard-video-result.json`. Grouped long-film review/Resume and frozen retry are regression/compiled checks, not another multi-hour real film. |

## Recorded media profiles for operator instructions

- **Video, short standard:** Wan2.2 5B, 1280×704, 33 frames, 24 fps,
  20 steps, seed 43; actual Qwen3.5 9B translation followed by actual GPU video.
  Source: `media-language-workflows-20261025/real-standard-video-result.json`.
- **Video, long draft:** 60 seconds, 1280×704, 1440 target frames, four steps,
  17-frame carried motion context; approximately 92 minutes in the historical
  run. Source: `long-media-20261014/real-result.json`. Duration/assembly proof
  does not establish standard-profile visual quality or exact scene fidelity.
  Review of archived frames 80/719/1439 on 2026-10-25 found progressive loss of
  detail and severe cyan saturation/posterization. Its technical pass is retained;
  visual standard-quality acceptance is false. Evidence:
  `long-media-visual-audit-20261025/review.json`. A separate actual ten-second,
  four-window/20-step bounded-profile check is in progress, not yet a pass.
- **Avatar, bounded short:** five seconds, 384px, eight steps, two native windows,
  about four minutes; actual 11-GiB RAM/zero-swap profile, complete video/audio
  decode, basic face/join samples and compiled playback. Exact word lip-sync is
  unqualified. Source: `echo-memory-profile-20261024/post-deployment-qualified.json`.
- **Avatar, longer:** 30 seconds, 384px, eight steps, about 35 minutes. Repeated
  existing generated QA speech plus silent tail; full decode and sampled joins
  passed, with gradual drift and hand artifacts recorded. This is not fresh
  long narration or broad identity/lip-sync qualification. Source:
  `long-avatar-default-20261015/result.json`.
- **Music, agent:** ten-second instrumental ACE-Step, actual GPU/native execution
  and published WAV. Source: `agent-media-generation-20261023/real-agent-media-result.json`.
- **Krea:** use only the prepared Q4 GPU-only profile and exact parameters in
  `krea2-lustify-20261025/`; the unused FP8 file is not a qualified alternative.

Catalog minutes are planning estimates, not runtime promises. Long-media cases
must disclose the concrete selected profile and historical duration rather than
promising completion within a generic five/fifteen-minute row estimate.

## Finite next release gates

1. The goal-prepared video chain is now actually qualified in
   `agent-video-release-20261025/`: real 9B natural draft/goal preparation, two
   GPU windows, complete five-second/120-frame 1280×704 film, sampled joins and
   actual 1440px/390px compiled playback. The earlier false receipt is retained.
   This used an explicitly reviewed 7200-second allowance. PR #448 qualifies
   new disabled proposals with a controller suggestion when no runtime was
   requested; actual 9B checks preserve an explicit five-minute limit as 300.
   Existing definitions and running allowances are unchanged; deployment receipts
   determine which correction is live.
2. Decide and verify the declared quality envelope for longer Video/Avatar
   against actual output, not merely decode/readiness. Retain the user's longer
   media requirement; do not silently drop it or relabel known drift as perfect.
3. Complete owner-controlled Tailscale enrollment/HTTPS and an actual remote
   device connection. Current installed `NeedsLogin` is an observed open gate.
4. With an owner-configured mail account and explicitly reviewed message/recipient,
   verify actual delivery without exposing credentials or sending invented mail.
   There is no email connector in the current application DB.
5. Freeze the release after remaining fixes, generate the final Polish XLSX/CSV
   package with fixtures and exact profiles, inspect/round-trip the actual files,
   and hand it off. All 157 operator results remain **Nie testowano**.

The original self-development/large IDE expansion is explicitly deferred by the
agent-first decision; existing data and functioning code/worktree services are
preserved. Future nodes/connectors remain honest unavailable/planned capabilities
rather than invented working integrations. This review does not close that full
future roadmap or the current platform goal.
