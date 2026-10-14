# Separate System from Settings

Status: **delivered in PR #270**, 2026-10-14. See [current Settings behavior](../settings.md)
and the [delivery brief](2026-10-chat-work-media.md). The root cause below is the
historical baseline, and this specification remains the regression contract.
Do not create another Settings implementation.

## Root cause and decision

`frontend/src/App.tsx` mounts `<System />` at both `/system` and `/settings`.
`System.tsx` combines telemetry, checks, worker leases, `OperatorAccess`,
`Maintenance`, `ChatProviders`, `Connectors` and `RuntimeObservations` in one page.
The duplicate screens are routing/composition, not missing backend functionality.

Create a real Settings route with compact section navigation. Move existing
configuration components intact first; improve their layout in place. Keep System
as the live workstation view. Do not duplicate CRUD or invent new endpoints to
rename a page. Home remains the cross-workspace activity dashboard.

## Information ownership

| Canonical destination | Content | Existing implementation to reuse |
| --- | --- | --- |
| `/system` | GPU/VRAM/process observations, CPU/RAM/disk, worker/scheduler/Runner status, active leases and runtime observations | Hardware/status APIs, `GpuProcesses`, `WorkerCards`, `LeaseHealth`, `RuntimeObservations` |
| `/system/diagnostics` | Actual integration checks, timestamps, refresh, unavailable/misconfigured distinctions | `/api/system/diagnostics`, `CheckCards` |
| `/settings/general` | New-conversation default mode/model, send-key preference and supported UI preferences | Typed `conversation_preferences` in existing Setting table; conversation plan |
| `/settings/providers` | Local/external endpoints, configured models, secret reference/presence, provider enable/delete | `ChatProviders` and existing provider APIs |
| `/settings/integrations` | Named connector configuration, state and explicit health-check action | `Connectors`; no fake mail/calendar/social setup |
| `/settings/access` | Operator password/session control, concrete security state | `OperatorAccess`; preserve current-secret verification and secret redaction |
| `/settings/maintenance` | Database backup/check/download, deployment readiness, safe existing operations | `Maintenance`; restore/rollout remain unavailable until separately implemented |
| Models / Projects / Agents | Their existing domain-specific configuration | Keep their dedicated workspaces and link from Settings when useful |

Settings root redirects to General; System root opens its own overview. Settings
may link **Check installation** to System diagnostics rather than render another
copy. System may link **Configure provider** to Settings Providers. No telemetry
polling or GPU refresh on a Settings-only form except a narrow required status.
Do not turn environment-only runtime paths into editable UI fields without a
separate validated configuration/restart contract.

## Compatibility and implementation

- Add `pages/Settings.tsx` and nested sections via React Router; support direct
  hash URLs and refresh. Use the existing component/library/style system.
- Change `App.tsx` routes and command-palette destinations. Preserve current
  `/system` bookmarks. Redirect known old focus links such as
  `/system?focus=maintenance` to `/settings/maintenance` using replace, not a loop.
  Search the repository for focus links and preserve each actual existing target;
  unknown query parameters must not trigger actions.
- Move configuration sections out of `System.tsx`; do not copy their forms.
  Extract diagnostic/lease components only as needed for the new subroute.
- Update `Maintenance`, provider/connector error links, README/operations docs and
  tests referencing System configuration. Keep APIs and permission checks unchanged.
- General preferences use a strict schema with a version token. Save on explicit
  Apply or discrete confirmed control change, with visible saved/error state.
  Reload restores them. Do not mutate an active conversation or live Run.
- Opening a section performs read-only requests. Only explicit buttons submit
  provider changes, password rotation, connector checks or backup Runs.
- Narrow viewport uses a compact section selector/drawer; focus returns to the
  control that opened it. Each route has a unique heading and document title.

## Acceptance

1. System and Settings have distinct headings, content and canonical routes.
   System shows live state and no provider, connector-edit or password form.
2. Every existing operational control is reachable once in Settings and still
   saves/loads correctly; no feature disappears during extraction.
3. Old maintenance links and palette items open the correct new section. Back,
   forward, refresh and direct links work on desktop and mobile.
4. Read-only navigation triggers no POST/PUT/DELETE. Secrets never appear in
   payload responses, errors, DOM, URLs or snapshots.
5. Worker/GPU status continues updating in System. Settings does not repeatedly
   poll all telemetry while editing a provider.
6. No new fake controls for LAN exposure, driver installation, arbitrary paths,
   model downloading or restore. Existing unimplemented operations stay honest.

Validate relevant React routing/component tests and browser navigation, followed
by frontend lint/typecheck/build. Backend checks are needed only if typed preference
storage changes; splitting views alone does not justify a full hardware smoke.
