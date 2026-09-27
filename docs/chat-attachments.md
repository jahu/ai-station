# Text attachments in local Chat

The composer reads explicitly selected UTF-8 files in the browser. The API accepts structured filename/content pairs, never a host path or URL. Up to four files are allowed, at most 16,000 UTF-8 bytes each and 24,000 combined; duplicate names, path-like names, null bytes and oversized serialized context are rejected before creating messages or Runs.

The original user prompt remains visible separately. A bounded JSON representation of attachment names/content is persisted in the user message as reference data and snapshotted into the ordinary Chat Run context. Existing recent-message windows, cancellation and local-provider restrictions apply unchanged. Regeneration reuses the same persisted source text; summary coverage includes attachment text rather than silently discarding it. Attachments in another conversation never enter this context.

Each uploaded text is also a general Artifact with a UUID storage filename, hash, original filename, source conversation/message and initial Run. Storage always uses `.txt` and `text/plain`; downloads carry attachment disposition and `nosniff`, including files originally named `.html`. The browser does not render uploaded markup. No separate execution engine or migration is introduced.

The limits intentionally target snippets and notes. PDF extraction, images/vision and binary/archive parsing remain unsupported. A model may misunderstand file contents; attachment boundaries are context labels, not a guarantee against prompt injection. The Chat executor has no tools or host filesystem access.
