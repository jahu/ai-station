# One Chat model catalog

Entry, saved conversations and General settings now share one searchable picker.
It groups **Local · llama.cpp**, **Local servers** and **External**. A selection
contains the provider and model together; the happy path has no separate provider
dropdown, manually typed model ID, context/GPU form or Load button. Dedicated
Models/runtime management and advanced conversation settings remain available.

`GET /api/chat/model-catalog` is a typed projection of the existing provider,
model-file, curated-definition and owned-runtime records. It starts no workload,
does not inspect model contents, and contacts no model endpoint by default.
Stable refs retain `llamacpp:<file-id>` or provider + encoded model identity.
The response exposes display names, local/external location, runtime kind, file
size/quantization, known availability, capability provenance and provider version.
It omits host paths, secret values and secret-reference names.

Installed unloaded GGUFs say **Loads when needed**; a known missing file is
disabled with its reason. Unknown owned runtime identity requires inspection.
A configured server default is **Configured**, not proof that the model is loaded
or that inference succeeded. **Browse … models** explicitly requests discovery
from just that provider via `?discover_provider=<key>`. No completion or paid token
request is made. A configured default absent from its endpoint's reported list
stays Configured. An offline server does not hide independent owned GGUFs.

Choosing a GGUF changes selection only. First Send retains the existing managed
load prerequisite, runtime ownership, resource reservations and local Coding's
larger fitted context. Selecting an external model is visibly external; no local
failure automatically switches to cloud. Normal capability/review policies remain.

Turn requests may include `expected_provider_version`. A stale version rejects
before enqueue; accepted receipt replay returns the original identities even if
the provider subsequently changes. Built-in provider reads now retain their
version until actual configuration changes. Run snapshots include the provider
configuration version alongside the existing endpoint/location/secret reference.
Older clients and receipts remain compatible, including hashes from before the
optional new-project scope was introduced. A changed prompt/scope/version under
an already accepted request UUID remains a conflict.

Reasoning has no verified per-turn mapping yet and is not exposed as a fake slider.
The catalog reports that state. Automatic modality/context-based model routing,
reasoning qualification and remaining Work/media increments are separate work.

Verification uses temporary DBs/fake endpoints for projection, absent/unknown
models, secret redaction, explicit discovery, provider-version guards and legacy
receipt replay, plus frontend choice/first-Send tests. Read-only Chromium at
1440/390 selected an actual installed 27B model using isolated copies of model,
definition, runtime and provider metadata; zero Tasks/Runs were created. The
production database, weights and external services were not modified by that
check. No new GPU or external inference smoke is claimed. Evidence:
`data/acceptance/unified-model-picker-20261014`.
