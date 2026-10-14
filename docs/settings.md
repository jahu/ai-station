# Settings and System

Settings is configuration, separate from live workstation observations:

- **General** saves typed new-conversation model/provider/mode defaults and the
  shared Chat send shortcut, using versioned preferences. Saving starts no workload.
- **Providers** retains existing endpoint/model and write-only secret configuration.
- **Integrations** retains the actual named connector registry and explicit checks.
- **Access** retains operator password/session controls and current exposure policy.
- **Maintenance** retains SQLite backup/check/download and deployment readiness.

System shows hardware observations, GPU processes, runtime observations, workers
and leases. **System → Integration diagnostics** opens the read-only installation
checks. Settings links to that page rather than duplicating diagnostics. Model,
project and agent configuration stays in its dedicated workspace.

Routes are `/settings/general`, `/settings/providers`, `/settings/integrations`,
`/settings/access`, `/settings/maintenance` and `/system/diagnostics`. Settings root
redirects to General. The old `/system?focus=maintenance` bookmark redirects to
Maintenance; the command palette uses the canonical route. Opening a section
submits no work. Existing provider, connector, access and maintenance APIs remain
unchanged. Settings does not poll all workstation telemetry; the local model
picker reads the narrow hardware information it needs.

The send shortcut applies to the entry and existing conversation composers:
Enter (Shift+Enter for newline), or Ctrl/Command+Enter. IME composition never sends.
Choosing Chat/Work or another default does not rewrite active Run parameters.
Saved feedback disappears when the editor changes again.

This implements the [System/Settings separation plan](plans/system-settings-separation.md).
Frontend integration tests cover saving preferences without a Run, canonical
navigation, the old maintenance bookmark and retained diagnostic/lease keyboard
behavior. Read-only browser and deployment evidence is recorded separately.
