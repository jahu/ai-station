"""Private semantic Studio coordinates; no execution or model-generated authority.

The assistant workflow bridge must be qualified before advertising a Studio tool.
These boundaries retain one frozen brand/options source and canonical media aliases.
"""

import json
from typing import Annotated, Literal

from pydantic import Field, model_validator
from sqlalchemy import select

from app.creative_projects import Defaults, get_project, snapshot
from app.models import Artifact, CreativeProject
from app.studio_materials import source_snapshot
from app.studio_schema import Fields

Alias = Annotated[str, Field(min_length=1, max_length=100)]
MAX_PROJECTS = 20
CONTEXT_BYTES = 24000


class StudioIntent(Fields):
    project: Alias | None = None
    project_resolution: Literal["standalone", "selected", "clarify"] = "standalone"
    format: Literal["reel", "presentation", "film"] | None = None
    aspect: Literal["portrait", "landscape", "square"] | None = None
    audio: Literal["voice_music", "voice", "music", "silent"] | None = None
    duration_seconds: int | None = Field(default=None, ge=5, le=600, strict=True)

    @model_validator(mode="after")
    def resolved(self):
        if (self.project_resolution == "selected") != bool(self.project):
            raise ValueError(
                "Select one supplied creative-project alias or leave the project unresolved/standalone"
            )
        return self


class StudioCall(Fields):
    instruction: str = Field(min_length=1, max_length=10000)
    title: str = Field(default="New material", min_length=1, max_length=160)
    references: list[Alias] = Field(default_factory=list, max_length=12)
    outcome_index: int | None = Field(default=None, ge=0, le=7, strict=True)
    presenter_reference: Alias | None = Field(default=None, exclude_if=lambda value: value is None)
    presenter_placement: Literal["auto", "right", "bottom"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.references)) != len(self.references):
            raise ValueError("Choose each supplied media reference once")
        if self.presenter_placement and not self.presenter_reference:
            raise ValueError("Choose the supplied presenter image before its placement")
        return self


def project_catalog(session, *, owner_id, location):
    # Do not even read private brand descriptions for an external provider.
    if location != "local":
        return {}
    rows = session.scalars(
        select(CreativeProject)
        .where(CreativeProject.owner_id == owner_id, CreativeProject.archived_at.is_(None))
        .order_by(CreativeProject.updated_at.desc(), CreativeProject.id.desc())
        .limit(MAX_PROJECTS)
    )
    result, used = {}, 2
    for row in rows:
        frozen = snapshot(session, row.id)
        public = {
            "name": frozen["name"],
            "aliases": [a[:100] for a in frozen["aliases"][:6]],
            "description": frozen["description"][:400],
            "language": frozen["identity"].get("language", "")[:80],
            "tone": frozen["identity"].get("tone", "")[:200],
            "defaults": frozen["defaults"],
        }
        alias = f"brand:{row.id}"
        cost = len(json.dumps({alias: public}, ensure_ascii=False).encode()) + 1
        if used + cost > CONTEXT_BYTES:
            break
        used += cost
        result[alias] = {"snapshot": frozen, "public": public}
    return result


def public_projects(catalog):
    return {alias: value["public"] for alias, value in catalog.items()}


def resolve_project_alias(project, catalog):
    """Bind a model-selected captured name/domain, never infer intent from words.

    The catalog advertises both opaque keys and human-facing project aliases.
    Exact unambiguous advertised labels denote that same frozen resource; no
    substring/fuzzy/domain discovery or new project authority is introduced.
    """
    if project in catalog:
        return project
    label = project.strip().casefold()
    matches = [
        alias
        for alias, entry in catalog.items()
        if label in {str(v).strip().casefold() for v in [entry["name"], *entry.get("aliases", [])]}
    ]
    if len(matches) != 1:
        raise ValueError(
            "Choose one unambiguous supplied creative-project alias; clarify an unknown or shared name"
        )
    return matches[0]


def selected_context(session, catalog, intent):
    """Only a server-captured alias selects a brand; overrides come from frozen intent."""
    if intent.project_resolution == "clarify":
        raise ValueError("Clarify the intended creative project before producing material")
    frozen = None
    if intent.project:
        entry = catalog.get(intent.project)
        if entry is None:
            raise ValueError("Choose a supplied creative-project alias")
        frozen = entry["snapshot"]
        # Recheck scope and archival authority; a historical identity snapshot
        # grants no permission to a removed, foreign or archived project.
        get_project(session, frozen["id"], active=True)
    base = dict(frozen["defaults"]) if frozen else Defaults().model_dump()
    for key in ("format", "aspect", "audio", "duration_seconds"):
        if (value := getattr(intent, key)) is not None:
            base[key] = value
    return {
        "creative_project_id": frozen["id"] if frozen else None,
        "project_snapshot": frozen or {},
        "options": Defaults.model_validate(base).model_dump(),
    }


def reference_ids(session, *, owner_id, entries, aliases):
    """Uploaded/generated images and footage use existing exact owner-bound aliases."""
    if len(aliases) > 12 or len(set(aliases)) != len(aliases):
        raise ValueError("Choose up to twelve distinct supplied media references")
    result = []
    for alias in aliases:
        entry = entries.get(alias)
        if not entry or entry.get("type") not in {"image", "video"}:
            raise ValueError("Choose supplied image/video reference aliases")
        item = session.get(Artifact, entry["snapshot"]["id"])
        if item is None or item.owner_id != owner_id:
            raise ValueError("The reference owner changed")
        current = source_snapshot(session, item.id)
        expected = entry["snapshot"]
        if (
            current["sha256"] != expected["sha256"]
            or current["size_bytes"] != expected["size_bytes"]
            or current["relative_path"] != expected["relative_path"]
        ):
            raise ValueError("The supplied media reference changed")
        result.append(item.id)
    return result
