# Content-preserving model source recovery

NR-14 requires recovery from stale public model links. Extend the existing
reviewed-file downloader rather than adding a second download service, arbitrary
URL input, model search agent or schema. Work remains inside the owned download
Run with its existing permissions, storage admission, lease, cancellation,
deadline, partial-file lock and final hash/length verification.

After reviewed Hugging Face file sources return HTTP 404/410, inspect bounded
public metadata for the same repository. Accept a new immutable commit URL only
when the same filename's LFS SHA-256 and exact length match the frozen reviewed
FileSpec. Never adopt a new model, quantization, license, filename, expected hash
or size from current upstream metadata. An incompatible/missing file remains a
clear failure with its partial preserved; authentication and rate limits do not
trigger an attempted bypass. Successful original URLs and cached bytes require
no metadata request.

Use the existing public-DNS-pinned HTTPS transport for metadata and recovered
bytes; recheck redirects, bounded body, ordinary Run cancellation and deadline.
Resolve at most once per failed retrieval and reuse repository metadata within
that attempt. Keep every catalog fingerprint and durable model coordinate stable.
Record an owner-scoped `model.download.source_refreshed` event before attempting
the new immutable source. Metadata resolution does not claim completed bytes.

Qualification must cover unchanged-content success, changed/missing/ambiguous
identity refusal, malformed/oversized metadata, non-HF/unpinned/query/unsafe
URLs, denied/private redirects, cancellation and lease propagation, no metadata
for success/cache/non-404 failure, retained partial resume and unchanged complete
file verification/publication. Use tiny fake objects and fake HTTP normally;
an opt-in public metadata-only check may verify the actual publisher schema
without downloading weights. Include worker event/privacy integration and update
documentation only to the evidence actually obtained.

The publisher documents its [public Hub API](https://huggingface.co/docs/hub/api).
This feature does not complete broader hardware/catalog, platform installation
or final release acceptance requirements.

## Implementation and qualification

`model_download_files.obtain` attempts reviewed sources first. Missing-source
exceptions retain their actual HTTP status so recovery is limited to 404/410.
The resolver checks only the failed, already reviewed HF URLs, caches at most
four repositories within the attempt and limits each metadata body to one MiB.
It accepts exactly one matching LFS entry and a different 40-hex commit; mutable
branches, ambiguous filenames and changed bytes cannot become download sources.
Both existing workers publish the same private source-refresh event and recheck
their claim/authority before doing so. No schema or catalog identity changes.

A real public metadata-only probe resolved the first catalog 4B Q4 file's exact
reviewed SHA-256 and 2,497,281,312-byte identity from its publisher metadata. The
probe used a synthetic old revision to exercise locator comparison and requested
no model bytes. It does not establish that a real publisher URL had expired.
Normal tests use tiny synthetic bytes and mocked metadata/HTTPS. Automated
successes are development evidence, not prefilled operator QA answers.
