# Versioned agent Skills

Skills are instruction packs, not plugins. An installed skill is a directory under the skills root containing a UTF-8 `SKILL.md` with YAML frontmatter. Selecting a skill copies that text into the agent's local report prompt. It does not grant tools, permissions, network access, filesystem edits or the right to run commands.

## Layout

The default root is `<data>/skills`. Set `AI_STATION_SKILLS_DIR` to use another directory. Each skill lives at `<root>/<id>/SKILL.md`. The directory name must match the `id` field. Symlinked roots, skill directories or `SKILL.md` files are rejected. Invalid documents are omitted from the catalog; selecting a missing or invalid id fails closed.

```text
---
id: daily-brief
name: Daily brief
version: 1.0.0
description: Local status report format
required_permissions:
---

Always mention GPU memory when it appears in the observations.
Cite only supplied tool results. Do not invent host actions.
```

`id` is `a-z` then up to 62 `a-z0-9-` characters. `version` is `x.y.z` with each component at most three digits. Frontmatter is simple `name: value` lines; nested YAML, tags and lists other than a comma/space-separated `required_permissions` field are not parsed. Documents are limited to 16 KiB. Instruction body text is limited to 8,000 characters, and a Run may attach at most four skills whose combined instructions stay under 24,000 characters.

`required_permissions` names existing AI Station permissions. They are a declaration, not a grant. The agent's selected tools must already provide those permissions or saving the definition fails.

## Lifecycle

The Agents editor lists installed skills from `GET /api/skills` and never invents ids. Arrow keys move through that list; Space or Enter selects the focused skill. Review the instruction text before enabling the agent. There is no inspectable Skill Run. Natural-language draft creation may attach an installed skill when the instruction mentions its id or name; the draft stays disabled. After `agent.create`, the conversation shows those attached skills from the same catalog; Review instructions stays on the selected row. A stored id that is not installed stays visible and is not invented. Space or Enter does not select or start a Run.

Queueing a Run snapshots the selected documents, including hashes, into `run.parameters["skill_snapshots"]`. The worker re-reads the files and fails the Run if a hash changed, a skill was removed, or the files are no longer readable. Verified ids, versions and hashes are recorded as a `skills.verified` event. Cancellation still closes the model stream; skill files are not processes.

Skill text is untrusted reference, like tool observations and memory. The report prompt says so explicitly. Skills cannot register tools, call the Host Runner, or choose URLs.

## Out of scope

Cursor/Codex host skills, executable plugins, package installers, automatic download of skill directories, and model-selected skill ids at runtime are not implemented.
