# Studio materials and editorial versions

Studio materials are independent of software Projects and Git. A material has
an optional creative project, a brief and format/aspect/length/audio preferences.
Its immutable editorial revisions retain the exact brief, preferences, identity
snapshot, source observations and parent version. Archiving preserves history;
optimistic edits cannot overwrite another browser's newer work. Creation and
revision receipts are idempotent. Migration 0047 adds separate collections and
does not rebuild existing creative sessions or change their generators.

The account policy treats materials as private roots and revisions as inherited
records through their material and optional source Run. A foreign project,
revision, source Artifact or Run cannot be attached. Administrator inspection
remains explicitly read-only. Library sources are live image/MP4 artifacts,
canonical below app storage, hash-observed and checked again in the worker.

`/studio` and each project list materials as well as existing creative assets.
A material opens a storyboard workspace: numbered shots, their narrative
purpose, visual direction/framing, on-screen text, narration and sound direction.
Scene edits/reordering create a new version. Earlier versions remain selectable;
unsaved edits block replanning/version switching. Materials can be archived and
restored. Desktop gives the storyboard the main area; mobile presents a saved
storyboard before the refinement controls.

The director is a normal queued `studio.plan` Task/Run, executed by
`studio_director` through the selected local provider. Managed llama.cpp uses
existing model preparation, dependencies and resource ownership. No inference
runs in an HTTP handler. Streaming has cancellation, a twenty-minute absolute
budget, a bounded response and one schema correction. Success stores a JSON
Artifact, a revision and structured events. Failure/Stop retains existing
versions and never publishes a partial plan as generated media.

The structured storyboard separates narrative intent from runtime settings.
Each shot chooses planned image/video, an existing Library source or deliberate
editorial graphics. It includes framing, motion, timing and actual spoken words.
No shell, HTML, tools, arbitrary source paths or URLs are executable input.
Requested voice/music policy cannot silently disappear. Sources can only come
from the supplied owner-scoped catalog. Source descriptions are not claimed as
visual inspection; model output is a plan, not evidence that assets were made.

This increment does **not** execute shot generation, speech/music synthesis,
render/export or Chat project inference. The isolated renderer is available as
a separately qualified native component; the director's planned assets must
next be connected to actual child Runs and observed before composition. Final
publication-quality acceptance requires a complete generated voiced/scored reel
and educational film with playback/visual review, not just a valid storyboard.
