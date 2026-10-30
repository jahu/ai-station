import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Plus, Search, ShieldCheck, Users, X } from "lucide-react";
import { api } from "../api";
import { useAccount, type AccountUser } from "../account-context";
import { Button } from "../components/ui/button";
import { Empty, ErrorNotice, Loading } from "../components/common";
import AccountInspection from "./AccountInspection";

const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const KEY = ["account-users"];

function UserDialog({
  user,
  lastAdmin,
  onDone,
}: {
  user: AccountUser | null;
  lastAdmin: boolean;
  onDone: () => void;
}) {
  const account = useAccount();
  const cache = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [factor, setFactor] = useState("");
  const [resetMfa, setResetMfa] = useState(!!user?.recovery_required);
  const [resetting, setResetting] = useState(false);
  const [enabled, setEnabled] = useState(user?.enabled ?? true);
  const [isAdmin, setAdmin] = useState(user?.is_admin ?? false);
  const [validation, setValidation] = useState<Error | null>(null);
  const save = useMutation({
    gcTime: 0,
    mutationFn: async () => {
      if (!user)
        return api<AccountUser>(
          "/admin/users",
          json("POST", {
            username,
            password,
            is_admin: isAdmin,
          }),
        );
      if (resetting)
        return api<AccountUser>(
          `/admin/users/${user.id}/credentials`,
          json("POST", {
            password: adminPassword,
            new_password: password,
            reset_mfa: resetMfa,
            ...(factor ? { second_factor: factor } : {}),
          }),
        );
      return api<AccountUser>(
        `/admin/users/${user.id}`,
        json("PATCH", {
          enabled,
          is_admin: isAdmin,
        }),
      );
    },
    onSuccess: async () => {
      setPassword("");
      setConfirmation("");
      setAdminPassword("");
      setFactor("");
      const selfChanged =
        user !== null &&
        user.id === account.user?.id &&
        (resetting || !enabled || isAdmin !== user.is_admin);
      onDone();
      if (selfChanged) await account.signOut?.();
      else await cache.invalidateQueries({ queryKey: KEY });
    },
  });
  const changes =
    !user || resetting || enabled !== user.enabled || isAdmin !== user.is_admin;
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !save.isPending) onDone();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="account-user-dialog"
          onEscapeKeyDown={(e) => {
            if (save.isPending) e.preventDefault();
          }}
          onInteractOutside={(e) => {
            if (save.isPending) e.preventDefault();
          }}
        >
          <div className="row spread">
            <Dialog.Title>{user ? user.username : "Add a user"}</Dialog.Title>
            <Dialog.Close
              className="icon-button"
              aria-label="Close user settings"
              disabled={save.isPending}
            >
              <X size={18} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted">
            {user
              ? "Manage this account’s access. Saved conversations and creations are retained when access is disabled."
              : "Give someone their own private conversations, Library and agents on this station."}
          </Dialog.Description>
          <ErrorNotice error={validation ?? save.error} />
          <form
            className="account-form"
            onSubmit={(e) => {
              e.preventDefault();
              setValidation(null);
              if ((!user || resetting) && password !== confirmation) {
                setValidation(new Error("Passwords do not match."));
                return;
              }
              if (!save.isPending) save.mutate();
            }}
          >
            <fieldset disabled={save.isPending} className="account-user-fields">
              {!user && (
                <label>
                  Username
                  <input
                    autoComplete="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    required
                    minLength={2}
                    maxLength={64}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                  />
                </label>
              )}
              {!resetting && (
                <>
                  <label>
                    Role
                    <select
                      value={isAdmin ? "admin" : "member"}
                      disabled={lastAdmin}
                      onChange={(e) => setAdmin(e.target.value === "admin")}
                    >
                      <option value="member">Member</option>
                      <option value="admin">Administrator</option>
                    </select>
                  </label>
                  <p className="account-field-hint">
                    {isAdmin
                      ? "Administrators manage users and the station, and can explicitly inspect all accounts’ data."
                      : "Members have their own workspace and share installed models and machine resources."}
                  </p>
                  {user && (
                    <label className="row">
                      <input
                        type="checkbox"
                        checked={enabled}
                        disabled={lastAdmin || !!user.recovery_required}
                        onChange={(e) => setEnabled(e.target.checked)}
                      />
                      Account enabled
                    </label>
                  )}
                  {lastAdmin && (
                    <p className="account-field-hint">
                      Keep at least one enabled administrator. Add another
                      administrator before changing this account’s role or
                      access.
                    </p>
                  )}
                  {user &&
                    (enabled !== user.enabled || isAdmin !== user.is_admin) && (
                      <p className="notice">
                        This change signs out their devices, pauses their agents
                        and cancels their queued or active work. Enabling access
                        does not restart paused work.
                      </p>
                    )}
                  {user?.recovery_required && (
                    <p className="notice">
                      Reset this account’s password and unavailable two-factor
                      authentication before enabling access.
                    </p>
                  )}
                </>
              )}
              {(!user || resetting) && (
                <>
                  {resetting && (
                    <p className="notice">
                      Resetting signs out every device for {user?.username}.
                      Give the new password to the account owner privately.
                    </p>
                  )}
                  <label>
                    {user ? "New password" : "Initial password"}
                    <input
                      type="password"
                      autoComplete="new-password"
                      required
                      minLength={12}
                      maxLength={200}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </label>
                  <label>
                    Confirm password
                    <input
                      type="password"
                      autoComplete="new-password"
                      required
                      minLength={12}
                      maxLength={200}
                      value={confirmation}
                      onChange={(e) => setConfirmation(e.target.value)}
                    />
                  </label>
                  <p className="account-field-hint">
                    At least 12 characters. Passwords cannot be retrieved later.
                  </p>
                </>
              )}
              {resetting && (
                <>
                  <label>
                    Your administrator password
                    <input
                      type="password"
                      autoComplete="current-password"
                      required
                      maxLength={200}
                      value={adminPassword}
                      onChange={(e) => setAdminPassword(e.target.value)}
                    />
                  </label>
                  {account.user?.mfa_enabled && (
                    <label>
                      Your authenticator or recovery code
                      <input
                        autoComplete="one-time-code"
                        required
                        maxLength={64}
                        value={factor}
                        onChange={(e) => setFactor(e.target.value)}
                      />
                    </label>
                  )}
                  {(user?.mfa_enabled || user?.recovery_required) && (
                    <label className="row">
                      <input
                        type="checkbox"
                        checked={resetMfa}
                        disabled={!!user?.recovery_required}
                        onChange={(e) => setResetMfa(e.target.checked)}
                      />
                      {user?.recovery_required
                        ? "Reset unavailable two-factor authentication"
                        : "Also reset this user’s two-factor authentication"}
                    </label>
                  )}
                </>
              )}
            </fieldset>
            <div className="account-user-form-actions">
              {user && (
                <Button
                  variant="ghost"
                  type="button"
                  disabled={save.isPending}
                  onClick={() => {
                    setResetting(!resetting);
                    setValidation(null);
                    save.reset();
                    setPassword("");
                    setConfirmation("");
                    setAdminPassword("");
                    setFactor("");
                    setResetMfa(!!user?.recovery_required);
                  }}
                >
                  {resetting ? "Back to access settings" : "Reset password"}
                </Button>
              )}
              <Button type="submit" disabled={save.isPending || !changes}>
                {save.isPending
                  ? "Saving…"
                  : !user
                    ? "Create user"
                    : resetting
                      ? "Reset credentials"
                      : "Save access"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default function AccountUsers() {
  const { user } = useAccount();
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<AccountUser | "new" | null>(null);
  const [inspecting, setInspecting] = useState<{
    user: AccountUser;
    trigger: HTMLButtonElement;
  } | null>(null);
  const users = useQuery({
    queryKey: KEY,
    queryFn: () => api<AccountUser[]>("/admin/users"),
    enabled: !!user?.is_admin,
  });
  if (!user?.is_admin)
    return (
      <Empty title="Administrator access required">
        Manage your own account in Account settings.
      </Empty>
    );
  const rows = users.data ?? [];
  const filtered = rows.filter((row) =>
    `${row.username} ${row.display_name}`
      .toLocaleLowerCase()
      .includes(search.toLocaleLowerCase()),
  );
  const admins = rows.filter((row) => row.enabled && row.is_admin).length;
  return (
    <section className="account-users" aria-label="Users">
      <div className="account-users-heading">
        <div>
          <div className="account-section-title">
            <Users size={20} />
            <h2>People on this station</h2>
          </div>
          <p className="muted">
            Private workspaces. Shared models and hardware.
          </p>
        </div>
        <Button onClick={() => setEditing("new")}>
          <Plus size={16} />
          Add user
        </Button>
      </div>
      <ErrorNotice error={users.error} />
      <label className="account-user-search">
        <Search size={16} />
        <span className="sr-only">Find a user</span>
        <input
          type="search"
          placeholder="Find a user…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
      {users.isPending ? (
        <Loading />
      ) : (
        <ul className="account-user-list">
          {filtered.map((row) => (
            <li key={row.id}>
              <div
                className={`account-avatar ${!row.enabled ? "disabled" : ""}`}
                aria-hidden="true"
              >
                {row.username.slice(0, 1).toUpperCase()}
              </div>
              <div className="account-user-identity">
                <strong>{row.display_name || row.username}</strong>
                {row.id === user.id && (
                  <span className="account-current-device">You</span>
                )}
                <p>
                  {row.username} · {row.is_admin ? "Administrator" : "Member"}
                  {!row.enabled ? " · Disabled" : ""}
                </p>
              </div>
              <span
                className={`account-user-factor ${row.mfa_enabled && !row.recovery_required ? "enabled" : ""}`}
              >
                <ShieldCheck size={14} />
                {row.recovery_required
                  ? "Reset required"
                  : row.mfa_enabled
                    ? "2FA on"
                    : "2FA off"}
              </span>
              <Button
                variant="ghost"
                aria-label={`Inspect workspace of ${row.username}`}
                onClick={(event) => {
                  setInspecting({ user: row, trigger: event.currentTarget });
                }}
              >
                <Eye size={16} /> Inspect workspace
              </Button>
              <Button
                variant="secondary"
                aria-label={`Manage ${row.username}`}
                onClick={() => setEditing(row)}
              >
                Manage
              </Button>
            </li>
          ))}
        </ul>
      )}
      {!users.isPending && !users.error && filtered.length === 0 && (
        <p className="muted">No users match your search.</p>
      )}
      {editing && (
        <UserDialog
          key={editing === "new" ? "new" : editing.id}
          user={editing === "new" ? null : editing}
          lastAdmin={
            editing !== "new" &&
            editing.is_admin &&
            editing.enabled &&
            admins === 1
          }
          onDone={() => setEditing(null)}
        />
      )}
      {inspecting && (
        <AccountInspection
          target={inspecting.user}
          onClose={() => setInspecting(null)}
          returnFocusTo={inspecting.trigger}
        />
      )}
    </section>
  );
}
