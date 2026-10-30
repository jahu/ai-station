# Accounts and private data

Implementation for [NR-11](plans/next-release-0.1.md) is in progress. The identity,
credential, session and optional authenticator services below are internal only.
The account API/profile is exercised on the real application in tests but is not
registered in the shipped application yet. Additional accounts remain inaccessible
until the complete ownership gate passes; a partial migration is not a release.

## Identity migration

Migration 0037 creates users, device sessions, personal settings and account audit
events. It reserves one administrator identity, without moving or deleting files.
On an existing installation it copies the operator's PBKDF2 password record and
hashed device sessions, preserving their expiry. No plaintext password or bearer
token is recovered or stored. A malformed existing credential requires explicit
local recovery; it must never open first-admin setup to a new claimant.

On a fresh installation the reserved administrator is disabled and pending setup.
Local first-admin setup supplies its username/password exactly once. Login names
use Unicode NFKC normalization and case folding for uniqueness; names are not
filesystem paths. Passwords use a random 16-byte salt and PBKDF2-SHA256 with
600,000 iterations. New passwords contain 12–200 characters. Public account
representations explicitly omit credential records, MFA references and recovery
hashes; secret-bearing result objects do not expose their fields through repr.

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

`ScopedSession` is staged separately from the live session factory. It binds an
immutable data scope, filters roots and dependent records before counts/limits,
and validates private references and writes. Missing scopes, raw SQL, bulk writes
and unknown model policies fail closed. Ownerless transitional rows stay
quarantined, including in general admin inspection. An identity-map lookup must
still validate ownership. Administrative inspection can read all owned private
data; it cannot silently create a new execution referencing another owner.
Worker execution uses a plain owner scope, without the admin inspection flag.

The explicit request-session factory rechecks the real account role and current
device, rather than accepting a caller's administrative flag. The worker factory
verifies the persisted Run against its frozen owner and rejects disabled accounts;
it does not grant admin inspection to an admin-owned agent. These factories still
need to replace the old request/worker session lifetimes at the cutover.

Personal provider/connector credentials use account-and-record namespaces. A
scoped user cannot select another record's file, an authenticator secret or a host
environment variable. Reference validation happens before replacing an existing
credential. The fixed built-in local-model endpoint may use its configured model
service credential; changing its endpoint cannot carry that credential elsewhere.
FTS mutation uses a small typed index-maintenance helper after an owner lookup,
within the same transaction. Search retains ownership filtering before limits.

These repository tests are not the HTTP privacy gate. The existing factory is
deliberately unchanged until authentication, worker/session lifetime, per-owner
credentials/settings, raw FTS mutations and the complete route inventory are
integrated. Additional user accounts remain unavailable through the application.

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
access. Per-owner embedding job bookkeeping and verified model-preparation writes
remain part of the execution cutover gate; a readiness GET is not proof that all
embedding execution paths are qualified.

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

Unreadable current authority cannot revive claimed accounts from a backup, even with the old
operator-password recovery flag. A named administrator recovery flow must be
provided for that case; the operator flag cannot silently replace an account's
password or bypass MFA. This remaining flow keeps the overall account cutover
gate open. Missing authenticator files never turn off an enabled second factor.

## Remaining enablement gate

- Add immutable owners/backfill to private roots and enforce them in repository
  operations, inherited child access, FTS, files, SSE, previews and cross-references.
- Bind workers/schedules/tools to the frozen owner while sharing only approved
  physical resources/models. Disable host-owner credential paths for ordinary users.
- Deliver bootstrap/login/admin/security UI, durable login/MFA attempt throttling,
  admin recovery, account-aware cookies and safe per-device logout. The staged
  UI and service/browser checks above are implemented; final profile enablement
  and offline administrator recovery are still pending.
- Preserve current credentials/MFA while offline recovery revokes old sessions.
- Namespace and clear browser queries, drafts, previews and object URLs between
  accounts; never briefly render the previous account's cached data.
- Execute the complete A/B/admin denial matrix from the recorded API inventory,
  legacy data preservation, desktop/mobile authentication and recovery checks.

Internal service tests prove only their stated credential/session/MFA contracts.
They are not evidence that the remaining application routes are owner-isolated.
