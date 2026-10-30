# Accounts and private data

Implementation for [NR-11](plans/next-release-0.1.md) is in progress. The opt-in
`AI_STATION_ACCESS_PROFILE=accounts` registers the account API and strict ownership
boundary in the real application, worker and scheduler. The production default
remains `operator` until the final preservation and privacy gates pass; the live
installation has not been switched. A partial migration is not a release.

## Identity migration

Migration 0037 creates users, device sessions, personal settings and account audit
events. It reserves one administrator identity, without moving or deleting files.
On an existing installation it copies the operator's PBKDF2 password record and
hashed device sessions, preserving their expiry. No plaintext password or bearer
token is recovered or stored. A malformed existing credential requires explicit
local recovery; it must never open first-admin setup to a new claimant.

First activation refreshes that staged identity from the current operator
password and devices, since operator logins or password changes may have occurred
after migration 0037. Removed or replaced devices are revoked; a replaced token
gets a new device ID, while unchanged devices retain their identity and expiry.
An explicitly revoked device stays revoked. Disabled accounts and administrative
roles are preserved. A missing or invalid legacy credential quarantines the
identity rather than opening setup. This refresh runs once, atomically with
ownership adoption; account-native credentials are never overwritten.

On a fresh installation the reserved administrator is disabled and pending setup.
Local first-admin setup supplies its username/password exactly once. Login names
use Unicode NFKC normalization and case folding for uniqueness; names are not
filesystem paths. Passwords use a random 16-byte salt and PBKDF2-SHA256 with
600,000 iterations. New passwords contain 12–200 characters. Public account
representations explicitly omit credential records, MFA references and recovery
hashes; secret-bearing result objects do not expose their fields through repr.

The staged first-start flow also supports a local browser whose connection
crosses Docker's bridge. At API startup, pending setup creates an owner-only
proof at `secrets/bootstrap/local-setup` beneath application data. The local
launcher obtains a private URL through the owned container console; no HTTP
endpoint returns this proof. Open that URL on the workstation to create the
administrator. Its fragment is removed immediately by the account screen and
kept only in memory until setup; it is never browser storage or an HTTP query.
An already-open setup screen can receive the link without losing its form.

Loopback Host validation and the existing private-access prohibition still apply.
A Docker/private source address or forwarding header never grants setup access.
The committed initial identity closes setup permanently; the proof file is
removed after success, and leftover files cannot reopen a configured or recovery
installation. Native loopback development retains its direct setup path. These
contracts are qualified on a disposable real Docker bridge and the compiled
desktop/mobile account screen; they do not enable accounts in the live profile.

When that profile is explicitly installed, private-network startup checks for an
enabled, configured administrator with a valid bounded password record. It does
not require or accept the retired operator credential as a substitute. Pending,
disabled, ordinary-member and recovery-required identities cannot unlock startup.
The dormant shipped profile retains its existing operator check, explicit origin
allowlist and loopback publish default; account readiness never grants a public
bind or configures a network service.

Staged private-connection operations use the current administrator's account
authority and an owner-bound standalone Run. Password/MFA changes invalidate
that approval; device sign-out alone does not cancel durable work. The worker
rechecks authority before dispatch and publication, inspects stale dispatched
actions instead of replaying them, and requests owned cancellation if authority
changes during execution. The existing native Tailscale ownership protocol stays
unchanged.

Only the fixed `private_ui_access` policy participates in this machine transaction.
Its versioned write is atomic with the owner's Run/events and cannot become a
general Setting/SQL grant. Ordinary scoped bulk SQL and read-only inspection
remain denied. Other administrators see only service health, policy revision and
busy/inspection facts; another account's Run, native daemon provenance, logs and
interactive sign-in links remain private. The UI explains shared activity and
offers an explicit Disable after an uncertain terminal operation without exposing
its originating account. Synthetic native transports qualify these contracts;
live account-profile Tailscale enrollment is not claimed.

If an account is disabled or demoted before a crashed private-access worker
recovers, trusted queue coordination can only cancel its already-dispatched,
structurally verified native action. It cannot issue an execution session, start
another action or change the shared connection policy. Cancellation uses the
frozen Run identity/operation and rechecks the claiming worker before recording
completion. Missing or mismatched proof retains cancellation state, leases and
reservations for later cleanup; raw native errors never enter account history.
An unknown action shape stays interrupted for inspection. Ordinary scoped and
read-only inspection sessions cannot borrow this cleanup authority. The UI
distinguishes cleanup still in progress from terminal work needing an explicit
Disable. Other executor families retain their own separate recovery contracts.

The real 0036 → current ownership-upgrade fixture also preserves private-action
and Task IDs, frozen parameters and shared connection policy. A historical
operator approval is not silently promoted into new account authority: work
which had not dispatched fails for renewed review; dispatched work is inspected
and its owned action canceled without another start. Completed connection
configuration/history is not rewritten. Request a new account-authorized action
after reviewing that interrupted upgrade work.

Services leave commit/rollback to their caller. Account audit events commit with
the successful operation. A downgrade refuses to discard identities after use;
restore a reviewed, stopped-service backup rather than erasing live accounts.

## Device sessions and administration

Each device has its own revocable, HMAC-verified random token. A SHA256 lookup
digest locates the record but cannot authenticate alone. Activity extends the
30-minute idle window without extending the 12-hour absolute expiry. At most ten
active devices per account are retained; another account's devices are unaffected.
Logout and device revocation apply only to the selected owned session. Device
lists do not return token material and cannot enumerate other accounts.

The account cookie is `ais_session`; migration compatibility may accept an old
`ais_operator` cookie. If an account cookie is present, including an invalid or
expired value, authentication never falls back to the old privileged cookie.
The HTTP cutover must clear both cookies on login/logout and retain existing
HttpOnly, SameSite, HTTPS secure-cookie and same-origin protections.

Only a currently authenticated administrator can create users or change roles.
There must always be an enabled administrator. Disabling an account or changing
its role revokes its devices; re-enabling it does not revive old cookies. A stale
principal cannot retain administrator authority. Password changes require the
current password and revoke all devices, including migrated operator sessions.
Compatibility endpoints must not remain an alternative password-only login.
Account removal will disable the identity and retain auditable historical data;
private-data deletion is a separate explicit operation.

## Optional authenticator

TOTP uses the pinned [PyOTP implementation](https://pyauth.github.io/pyotp/).
Enrollment requires the current password, expires after ten minutes and is bound
to the initiating device. MFA is enabled only after confirming a real six-digit
code. Confirmation preserves that verified device and revokes the others.
Login requires the password and, when enabled, an authenticator or recovery code
in the same operation; password verification alone cannot grant a session.

The verifier accepts at most one 30-second step of clock drift in either
direction. A consumed time step cannot be reused. Eight random 128-bit recovery
codes are shown once and stored as user-bound hashes. Each is consumed once;
regenerating them invalidates all previous codes. Regeneration and disabling MFA
require the current password plus a valid second factor. Disabling revokes all
sessions. Neither a missing secret nor an unverified historical cookie disables
MFA. Recovery codes remain usable when the authenticator file is unavailable.

Authenticator secrets live in 0600 files beneath a private per-account directory
under `secrets/accounts/`; the database contains references, not secret values.
Enrollment returns provisioning data only to the reauthenticated owner. It must
be rendered locally, never sent to an external QR service or analytics endpoint.
The complete application data root, including protected secret files, is needed
for a usable backup. Database-only restoration must not silently disable MFA.
Rollbackable database transactions do not delete secret files: expired/replaced
enrollment files can remain until a separately reviewed retention operation.

## Private repository boundary in development

Migration 0038 adds indexed owner references to ten private roots and backfills
the existing installation to its sole initial identity. All UUIDs and artifact
paths remain stable. Messages/events and the other dependent records inherit
access through their private parents. Only personal connector/provider uniqueness
needs a table rebuild: keys become unique per owner, so users may independently
call a provider `openai`, for example. Existing email-delivery references are
restored by exact ID within the migration transaction; preservation and foreign
key checks cover that relationship. Multi-user databases with ambiguous legacy
ownership are rejected instead of guessed. Downgrade is allowed only on an empty,
unused bootstrap installation; populated ownership cannot be discarded.

The account profile uses `ScopedSession`, while the live operator profile retains
its legacy session behavior. A scoped session binds an
immutable data scope, filters roots and dependent records before counts/limits,
and validates private references and writes. Missing scopes, raw SQL, bulk writes
and unknown model policies fail closed. Ownerless transitional rows stay
quarantined, including in general admin inspection. An identity-map lookup must
still validate ownership. Administrative inspection can read all owned private
data; it cannot silently create a new execution referencing another owner.
Worker execution uses a plain owner scope, without the admin inspection flag.

Versioned private mutations select and refresh the exact owner-filtered row under
a write lock before comparing the expected version. They change ordinary ORM
fields, retaining immutable-owner/reference validation on flush. Conversation
archive/context selection, Library edits/trash/restore, deletion intent and
agent/check-repeat locks use this path. Cached stale objects cannot replace the
locked snapshot, competing edits cannot both consume one version, and read-only
administrative inspection cannot acquire a mutation lock. Raw SQL and bulk ORM
writes remain denied to scoped requests and executors.

Worker and scheduler entrypoints request trusted coordination sessions explicitly;
their global claims, leases, due-agent enumeration and machine sampling do not
depend on an ambient user session. Each owned workload still executes inside its
frozen owner scope. The account profile rejects unbound repository access and
ownerless execution; only the explicit operator profile retains those legacy paths.

HTTP-derived scopes retain the authenticated device identity in memory only.
Every SSE batch revalidates device revocation, idle/absolute expiry, password/MFA
changes and current administrator authority for all-account inspection in the
same transaction as reading events. Terminated authority ends the stream with a
login-required transport notice; it does not change or cancel the durable Run.
The browser closes the connection, discards buffered events and opens the
existing sign-in boundary without flushing late private tokens.

The explicit request-session factory rechecks the real account role and current
device, rather than accepting a caller's administrative flag. The worker factory
verifies the persisted Run against its frozen owner and rejects disabled accounts;
it does not grant admin inspection to an admin-owned agent. The opt-in account
profile uses these factories for request and worker lifetimes.

Personal provider/connector credentials use account-and-record namespaces. A
scoped user cannot select another record's file, an authenticator secret or a host
environment variable. Reference validation happens before replacing an existing
credential. The fixed built-in local-model endpoint may use its configured model
service credential; changing its endpoint cannot carry that credential elsewhere.
FTS mutation uses a small typed index-maintenance helper after an owner lookup,
within the same transaction. Search retains ownership filtering before limits.

Repository tests alone are not the HTTP privacy gate. The account-profile HTTP
tests exercise authentication, worker/session lifetime, personal credentials,
settings and FTS. The complete route/execution audit and production switch remain
separate acceptance steps. The live installation still uses operator access.

## HTTP and execution integration in development

The account API provides local first-admin setup, username/password sign-in,
per-device logout/revocation, password rotation, administrator account policies
and reauthenticated credential/MFA reset, and authenticator enrollment/recovery.
Durable per-identity and global attempt budgets commit before verification; a
failed request cannot reset them, change casing or spoof a forwarded address to
evade them. Private API responses disable HTTP caching. Successful account
switching revokes the previous browser's device without revoking other devices.
Legacy operator cookies can migrate without extending their original expiry;
password-only compatibility endpoints are closed in the account profile.

The real monolith tests exercise A/B isolation for Runs, event lists and SSE,
Library files/Range/thumbnails/lineage, memory/FTS and personal preferences.
Administrator requests normally use their own data. Explicit all-account
inspection is restricted to read-only administrator requests, so it never
silently broadens an ordinary conversation's memory context. Machine management
and host-authenticated coding/GitHub operations require administrator authority.
This is partial route coverage, not the complete inventory acceptance gate.

Owner-bound Runs execute in a fresh scoped session, and secondary sessions inherit
the owner through request/execution context. An administrator-owned task does not
inherit the account's global inspection or configuration rights. Saved agent
scheduling uses that definition's owner, and disabled accounts cannot launch.
Changing a role or disabling an account pauses its agents, cancels queued work
and requests cancellation of active work using only that owner's scoped graph in
the same transaction. The worker performs native cancellation later; the account
HTTP handler never signals host processes. Re-enabling does not resume paused work.

GPU availability and total RAM reservations remain workstation-wide. Typed
admission helpers expose physical GPU keys and aggregate RAM, not another
account's Run IDs or prompts. Reservation records and release stay owner-scoped.

The final cutover must remove the transitional unbound-session/ownerless-execution
paths, integrate the remaining typed model/configuration/recovery and tool
boundaries, complete the route matrix and deliver the account-aware browser UI.
Do not deploy migration 0038 or enable the account profile on the workstation
before those gates pass.

## Browser integration in development

The staged frontend has first-admin setup, username/password and optional
authenticator/recovery-code login. Account settings provide password rotation,
locally generated authenticator QR codes, one-time recovery-code display and
individual device sign-out. Administrators have a user directory, account
creation, role/access changes and reauthenticated password/MFA reset. Both server
and UI preserve the last enabled administrator. Access changes explicitly explain
that devices are revoked, agents paused and queued/active work canceled.

Account changes unmount the previous workspace, clear private query/mutation
caches and browser drafts, and establish an account-specific storage namespace.
An epoch fences late JSON/text responses and buffered SSE events. Requests bind
to the expected browser account as well as the authenticated cookie, so an old
tab cannot accidentally write or sign out a newly logged-in account. Other tabs
lock on account-change events and recheck authentication. Unrelated application
storage is retained; passwords, setup keys and recovery codes are never persisted
in browser storage. Only an absent account API permits the old operator UI;
server/network failures show a reconnect state instead of falling back.

The account router is installed before a built-frontend catch-all mount. A real
compiled browser check on disposable SQLite exercises Alice/Bob login, reload,
private-state cleanup, administrator create/disable/reset, actual local QR/TOTP
enrollment and recovery login. Desktop and 390-pixel mobile layouts were inspected
with no horizontal overflow or JavaScript errors. This check never opens the live
workstation database and does not enable the profile on that installation.

Shared embedding-model readiness exposes owner-filtered counts/activity and
hides another account's Run IDs and machine credential references. Its fixed
internal configuration read does not grant a member administrative Settings
access. Preparation/health/index activity and learned dimensions are kept in
account-owned preferences bound to the exact model/revision. An account may index
or search its own memory while another account has an independent operation;
model preparation itself uses a workstation-wide busy check without revealing
the other account's Run identity. Shared model settings contain infrastructure
metadata rather than user activity IDs.

Only a running, owned preparation Run for the fixed approved CPU model can
activate shared configuration. Activation rechecks the live administrator role,
frozen revision/model identity and verified vector dimension. An execution session
gets neither generic machine-setting write permission nor admin-wide context.
Queued preparation also fails before dispatch after administrator demotion.
User-visible Run parameters omit machine credential references; the worker
resolves the current, revision-bound service credential internally.

A controlled CPU child and real API/worker checks cover Alice/Bob preparation,
private indexing/search/results, cross-account activity denial, shared busy
coalescing, role demotion and owner-only cancellation. These are synthetic
executor checks, not a claim that new embedding weights were downloaded or a
particular installed model was benchmarked. The remaining runtime/tool/request
audit is still required before enabling the overall account profile.

Historical migration tests now materialize their synthetic unowned rows in a
real Alembic-created legacy schema before upgrading. They do not bypass the
production prohibition on downgrading populated ownership. Legacy schemas and
fixture data are checked for foreign-key integrity before the upgrade.

## Offline account recovery in development

Restoring older data must retain current account authority, rather than the
backup's passwords, administrator roles, enabled flags, authenticator references,
consumed time steps or recovery-code hashes. Recovery snapshots this authority
read-only from the stopped current database and overlays it on the private staging
copy. Accounts added since the backup are retained. Historical account IDs absent
from current authority remain as disabled provenance owners with unusable old
passwords. Restored device sessions are revoked and abandoned authenticator
enrollments discarded. Current verification-attempt budgets are retained. The
ordinary recovery receipt contains counts, never password hashes, setup keys or
recovery hashes; the authority snapshot is held only in memory.

Identity collisions and legacy backups whose newly migrated initial owner differs
from the current identity fail before recovery is applied unless an operator
explicitly selects `--legacy-owner USERNAME` alongside `--apply` and the reviewed
backup digest. The selected account must exist in current authority. Mapping is
limited to one unambiguous pre-account/unused initial identity without account
MFA; it cannot reassign a backup containing multiple private accounts or a known
different current owner. Root UUIDs, dependent records, files and personal
preferences are retained; only the explicitly reviewed ownership changes. The
receipt records previous/current owner UUIDs. Bootstrap renaming and legitimate
reuse of the old `admin` username do not conflate the identities.

Unreadable current authority cannot revive claimed accounts from a backup, even
with the old operator-password recovery flag. A separate offline recovery option
requires the backup's existing administrator username, a new password and explicit
MFA-reset acknowledgement:

```bash
./scripts/restore.sh --backup-run <uuid> --apply --expected-sha256 <reviewed-digest> \
  --recover-admin <username> --reset-admin-mfa --admin-password-file <private-0600-file>
```

An interactive terminal can prompt securely instead of reading a password file.
Passwords never go on the command line or into reports. This operation is limited
to unreadable current account authority; it cannot replace readable current
authority or promote an arbitrary backup member. It cannot combine with operator
password replacement or legacy owner mapping. The selected administrator gets the
fresh password, its historical sessions/recovery codes are invalidated and the
explicitly acknowledged unavailable MFA is reset. Existing secret files remain
untouched for forensics/rollback. Other backup accounts are quarantined: login is
disabled, historical passwords are unusable, and an administrator must reset their
credentials and MFA before re-enabling them. Device sessions and abandoned MFA
enrollment are revoked for everyone. Data UUIDs and ownership are retained.
Private access remains disabled until reviewed; a recovered administrator does
not automatically reopen the network service. Normal recovery with readable
authority still preserves enabled MFA and current recovery hashes.

These are staged host-administration operations, outside HTTP and agent tools.
The complete account request/execution/tool boundary remains the enablement gate.

## Administrator workspace inspection (staged profile)

Settings → Users → **Inspect workspace** opens a separate read-only dialog for
one selected account. The header identifies both the subject and the actual
administrator; it does not log in as that user or replace the administrator's
ordinary workspace. Conversations/messages, Library (including Trash/deletion
history), Runs/events, Tasks, Memory (including disabled entries), Agents,
Projects, Approvals, model providers and connections have server-side search and
paging. Saved parameters and provenance remain inspectable alongside transcripts
and supported media previews. Named personal preferences are included; password,
TOTP/recovery material and arbitrary internal settings are excluded.

`GET /api/admin/users/{id}/workspace` and its fixed collection/detail/entries/file
routes revalidate the real administrator's device and role on each request.
They construct an explicit selected-owner, read-only `ScopedSession`: the actor
stays the administrator, while counts, paging, derived records and identity-map
lookups are restricted to the selected subject. Disabled subjects remain
inspectable. A disabled, demoted or revoked administrator cannot keep opening
their data. No inspection POST/PATCH/PUT/DELETE or executable actions exist.
Normal administrator API requests still return only that administrator's data.

Files reuse canonical artifact storage and existing deletion/internal-output
guards. Cookie-authorized subject-bound file URLs support native range playback;
they do not load whole videos into JavaScript or attach bearer tokens to URLs.
Private responses are not cached. HTML/SVG and other non-preview files remain
attachments under the existing `nosniff` policy. Provider/connection inspection
reads stored metadata without probing endpoints or resolving credentials; stored
secret values/references and unknown connector configuration keys are omitted.
Inspection query keys contain actor and subject IDs; closing the dialog cancels
requests and clears only those inspection caches. Changing the logged-in account
continues to use the global account epoch/cache boundary.

The focused A/B/admin tests cover all ten collections, counts/search/paging,
messages/events, cross-subject IDs and files, credential omission, read-only
writes, disabled subjects, revoked/demoted actors, range streaming and symlink
escape. These tests and the dedicated UI checks qualify this inspector only;
they do not activate accounts or replace the complete application audit below.

Library lineage uses an ORM-mapped JSON parent join, preserving selected-owner
filtering before distinct/order/limit. It no longer relies on raw SQL rejected
by private sessions. A real A/B HTTP regression checks both source/derived
directions and proves that newer foreign children cannot consume a private page.

## Remaining enablement gate

The strict startup candidate uses `AI_STATION_ACCESS_PROFILE=accounts` consistently
for API, worker and scheduler (including the shared Compose environment). It
installs the account routes without a custom app wrapper and refuses unbound
repository sessions. The default remains `operator` while qualification is in
progress; this is not a production rollout instruction.

Activation is one trusted lifecycle transaction, recorded as an account event
and a fixed profile receipt. A sole existing identity adopts ownerless legacy
roots, including records written after ownership migration while the operator
profile was still active. IDs, content, parameters, timestamps and file paths are
preserved. Ambiguous multi-user ownership blocks activation rather than guessing.
Once a receipt exists, later ownerless records are never adopted automatically.
Operator startup is refused for an activated or multi-user database.

Workers keep their heartbeat but do not claim/recover work before first-admin
setup finishes. Afterwards, an ownerless queued Run fails without execution;
uncertain dispatch/PID or active reservations instead require inspection and keep
their allocations. Released reservations do not block it. Ownerless schedules are
not enqueued. The explicit operator profile retains legacy behavior for migration
qualification. These contracts do not replace the remaining operation/sandbox
audit or authorize deployment of an incomplete private-data boundary.

Shared llama.cpp stop/restart, operation coalescing, context upgrades and idle
eviction now check a fixed cross-account busy projection. It returns only a
boolean for the selected managed model; it never loads another account's Run or
returns its ID, prompt, task, logs or dependency graph. Owner-only ORM views must
not make another account's active consumer look like an idle runtime.

Model-load intent may create one queued shared runtime from an owner-local load
Run. A request-scoped grant names that exact new ORM object and freezes its
generated fields; flush rechecks the owning Run, approved model observation and
fixed managed-runtime shape. It grants neither updates to an existing runtime nor
general shared-model/settings writes. Instance UUID planning precedes enqueue;
the worker still performs every host operation. A member's health request queues
an owner-local Run; shared health metadata changes when the worker completes.
Automatic preparation can plan a typed stop using a separate one-use grant:
only status and the exact owner-local stop reference may change. Direct HTTP
Stop/Restart remain administrator operations. Neither grant permits deleting a
runtime or changing its endpoint, model, name or other machine configuration.
Public runtime projections omit inaccessible operation provenance and raw server
error logs. Ready-model source and startup sorting use a minimal infrastructure
projection rather than loading another user's complete initiating Run.
Auto local-code selection uses the same shared source/device observations and a
fixed projection of measured context from the exact startup event. This includes
retained proof for a stopped model; no foreign prompt, full Run parameters or
event payload becomes available. The 100k/context-fit checks remain in place.
Shared model definitions also omit an inaccessible verification Run reference.
The model picker shows an inspection link only when that Run is accessible and
offers direct restart/unload only to an administrator; ordinary model selection
and health checks remain usable.
Model-file discovery references follow the same rule, including detached/global
records rendered in an owner context. Models shows ordinary users the shared
saved preset with its permitted load/health actions; discovery, definition edits,
installation, removal and runtime diagnostics remain administrator controls.
An already ready or changing runtime cannot be loaded redundantly from its card.

An account selecting a model another account is loading receives its own
`runtime.wait` Run. Only that private waiter is a consumer prerequisite; no foreign
producer ID or dependency enters the private graph. It freezes the model source
observation, instance and startup time, yields the worker with a two-second
backoff, and has a maximum ten-minute deadline bounded by the consumer's earlier
deadline. Failure, cancellation, replacement or expiry cannot replay the foreign
startup. Waiter cancellation never signals the model process. Recovery resumes
read-only observation without process inspection. Task Stop on the original
producer retains startup needed by another account.

A new load requested while another account stops the old instance uses the same
private waiter with a stopped target, bound to that stop's source and creation
observation. Reload dispatch requires successful confirmed shutdown; failed,
canceled or uncertain stop retains the existing allocation and fails the private
replacement prerequisite without leaking the stop Run ID.

After confirmed managed-runtime shutdown (`alive: false` and stopped/failed),
typed coordination releases only the exact loader's approved GPU and RAM
reservations. Another account's loader, Task, events and unrelated reservations
are untouched. Missing or live observations retain reservations. Synthetic
account/worker tests cover ready and pending shared-model consumption, server-log
redaction, cancellation/backoff/recovery/deadlines, Task retention and physical
release. This is not real multi-account GPU inference qualification.

Account revocation and model allocation have separate lifetimes. Trusted worker
coordination may inspect or shut down the exact already-dispatched managed model,
without restoring the disabled user's execution authority or launching it again.
If another enabled account still needs that model, loading is observed within
the original deadline; verified readiness cancels the initiating request while
retaining the shared model and its GPU/RAM reservations. A private readiness event
and an explicit retained marker provide only public source/device/context facts
to that account's waiter and Auto model selection. The initiating history stays
private. Normal in-flight cancellation follows the same shared-demand rule.

An unused model retains its reservations until native shutdown is confirmed.
The controller commits its stopping state before native I/O, so a concurrent new
request waits for actual shutdown before loading a replacement. Waiters recognize
confirmed physical shutdown even when the initiating request was canceled. A
revoked stop only observes the existing operation; it cannot issue a new stop.
Uncertain observations or changed model/worker bindings retain reservations and
require continued cleanup or inspection. Unknown dispatched executor families
also keep their allocations instead of becoming failed jobs with falsely free
GPUs. Queued, never-dispatched model cancellation retires only its exact owned
plan, preventing stale queued runtimes without granting general shared-row writes.
These are synthetic native-model/worker contracts, not real GPU revocation tests.

The remaining profile gate includes the complete operation inventory, larger
context/reload/handoff combinations and adversarial shared-resource qualification:

- Add immutable owners/backfill to private roots and enforce them in repository
  operations, inherited child access, FTS, files, SSE, previews and cross-references.
- Bind workers/schedules/tools to the frozen owner while sharing only approved
  physical resources/models. Disable host-owner credential paths for ordinary users.
- Deliver bootstrap/login/admin/security UI, durable login/MFA attempt throttling,
  admin recovery, account-aware cookies and safe per-device logout. The staged
  UI, named offline recovery and service/browser checks above are implemented;
  final profile enablement and the complete route/execution audit are pending.
- Preserve current credentials/MFA while offline recovery revokes old sessions.
- Namespace and clear browser queries, drafts, previews and object URLs between
  accounts; never briefly render the previous account's cached data.
- Execute the complete A/B/admin denial matrix from the recorded API inventory,
  legacy data preservation, desktop/mobile authentication and recovery checks.

Internal service tests prove only their stated credential/session/MFA contracts.
They are not evidence that the remaining application routes are owner-isolated.
