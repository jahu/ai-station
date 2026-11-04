import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { Check, Copy, KeyRound, ShieldCheck } from "lucide-react";
import { api } from "../api";
import { useAccount } from "../account-context";
import { copyText } from "../lib/clipboard";
import { Button } from "../components/ui/button";
import { ErrorNotice, Loading } from "../components/common";

const post = (body: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
type Enrollment = {
  secret: string;
  provisioning_uri: string;
  expires_at: string;
};
type Device = {
  id: string;
  label: string;
  current: boolean;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
};

function AuthenticatorQr({ uri }: { uri: string }) {
  const [src, setSrc] = useState("");
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => {
    let active = true;
    void QRCode.toDataURL(uri, { width: 192, margin: 2 })
      .then((value) => {
        if (active) setSrc(value);
      })
      .catch(() => {
        if (active)
          setError(
            new Error(
              "Could not create the QR code. Enter the setup key manually below.",
            ),
          );
      });
    return () => {
      active = false;
    };
  }, [uri]);
  if (error) return <ErrorNotice error={error} />;
  return src ? (
    <img
      className="account-qr"
      src={src}
      width={192}
      height={192}
      alt="Authenticator setup QR code"
    />
  ) : (
    <Loading />
  );
}

function RecoveryCodes({
  codes,
  onDone,
}: {
  codes: string[];
  onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<Error | null>(null);
  return (
    <section className="account-recovery" aria-label="Recovery codes">
      <h3>Save your recovery codes.</h3>
      <p>
        Each code works once if you lose access to your authenticator. These
        codes are shown only now.
      </p>
      <div className="account-code-grid">
        {codes.map((code) => (
          <code key={code}>{code}</code>
        ))}
      </div>
      <div className="row">
        <Button
          variant="secondary"
          onClick={() =>
            void copyText(codes.join("\n"))
              .then(() => setCopied(true))
              .catch((error: Error) => setCopyError(error))
          }
        >
          {copied ? <Check size={15} /> : <Copy size={15} />}
          {copied ? "Copied" : "Copy recovery codes"}
        </Button>
        <Button onClick={onDone}>I saved these codes</Button>
      </div>
      <ErrorNotice error={copyError} />
    </section>
  );
}

function PasswordSettings() {
  const { signOut } = useAccount();
  const [password, setPassword] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [validation, setValidation] = useState<Error | null>(null);
  const save = useMutation({
    gcTime: 0,
    mutationFn: () =>
      api("/account/password", post({ password, new_password: next })),
    onSuccess: () => {
      setPassword("");
      setNext("");
      setConfirm("");
      void signOut?.();
    },
  });
  return (
    <section className="panel account-settings-card">
      <div className="account-section-title">
        <KeyRound size={19} />
        <h2>Password</h2>
      </div>
      <p className="muted">
        Changing your password signs out all devices. Your saved work stays on
        this station.
      </p>
      <ErrorNotice error={validation ?? save.error} />
      <form
        className="account-form"
        onSubmit={(event) => {
          event.preventDefault();
          setValidation(null);
          if (next !== confirm) {
            setValidation(new Error("Passwords do not match."));
            return;
          }
          save.mutate();
        }}
      >
        <label>
          Current password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            maxLength={200}
          />
        </label>
        <label>
          New password
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={200}
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
        </label>
        <label>
          Confirm new password
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={200}
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
          />
        </label>
        <Button disabled={save.isPending}>
          {save.isPending ? "Updating…" : "Update password and sign out"}
        </Button>
      </form>
    </section>
  );
}

function TwoFactorSettings() {
  const { user, signOut } = useAccount();
  const cache = useQueryClient();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const enroll = useMutation({
    gcTime: 0,
    mutationFn: () =>
      api<Enrollment>("/account/mfa/enroll", post({ password })),
    onSuccess: setEnrollment,
  });
  const confirm = useMutation({
    gcTime: 0,
    mutationFn: () =>
      api<{ recovery_codes: string[] }>(
        "/account/mfa/confirm",
        post({ password, code }),
      ),
    onSuccess: (result) => {
      setRecovery(result.recovery_codes);
      setEnrollment(null);
      setPassword("");
      setCode("");
      void cache.invalidateQueries({ queryKey: ["account-auth"] });
      void cache.invalidateQueries({ queryKey: ["account-devices"] });
    },
  });
  const change = useMutation({
    gcTime: 0,
    mutationFn: (operation: "disable" | "recovery-codes") =>
      api<{ recovery_codes?: string[] }>(
        `/account/mfa/${operation}`,
        post({ password, code }),
      ),
    onSuccess: (result, operation) => {
      setPassword("");
      setCode("");
      if (operation === "disable") {
        setRecovery(null);
        void signOut?.();
      } else setRecovery(result.recovery_codes ?? null);
    },
  });
  const busy = enroll.isPending || confirm.isPending || change.isPending;
  return (
    <section className="panel account-settings-card">
      <div className="account-section-title">
        <ShieldCheck size={19} />
        <h2>Two-factor authentication</h2>
        <span
          className={`account-security-state ${user?.mfa_enabled ? "enabled" : ""}`}
        >
          {user?.mfa_enabled ? "On" : "Off"}
        </span>
      </div>
      <p className="muted">
        Protect sign-in with an authenticator app. The QR code is created
        locally; your setup key is never sent to a QR service.
      </p>
      <ErrorNotice error={enroll.error ?? confirm.error ?? change.error} />
      {recovery ? (
        <RecoveryCodes codes={recovery} onDone={() => setRecovery(null)} />
      ) : null}
      {!recovery && (
        <form
          className="account-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!user?.mfa_enabled) {
              if (enrollment) confirm.mutate();
              else enroll.mutate();
            }
          }}
        >
          <label>
            {enrollment
              ? "Confirm your current password"
              : "Password for two-factor settings"}
            <input
              type="password"
              autoComplete="current-password"
              maxLength={200}
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={busy}
            />
          </label>
          {enrollment && (
            <div className="account-enrollment">
              <AuthenticatorQr uri={enrollment.provisioning_uri} />
              <p>Scan with your authenticator, then enter the code it shows.</p>
              <a className="text-link" href={enrollment.provisioning_uri}>
                Open in authenticator app ↗
              </a>
              <details>
                <summary>Enter the setup key manually</summary>
                <code className="account-secret-key">{enrollment.secret}</code>
              </details>
            </div>
          )}
          {(enrollment || user?.mfa_enabled) && (
            <label>
              {enrollment
                ? "Authenticator code"
                : "Fresh authenticator or recovery code"}
              <input
                autoComplete="one-time-code"
                required
                maxLength={64}
                value={code}
                onChange={(event) => setCode(event.target.value)}
                disabled={busy}
              />
            </label>
          )}
          {user?.mfa_enabled ? (
            <div className="account-security-actions">
              <Button
                type="button"
                variant="secondary"
                disabled={busy || !password || !code}
                onClick={() => change.mutate("recovery-codes")}
              >
                New recovery codes
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={busy || !password || !code}
                onClick={() => change.mutate("disable")}
              >
                Turn off 2FA and sign out
              </Button>
            </div>
          ) : (
            <div className="row">
              <Button disabled={busy}>
                {busy
                  ? "Please wait…"
                  : enrollment
                    ? "Confirm and enable 2FA"
                    : "Set up authenticator"}
              </Button>
              {enrollment && (
                <Button
                  type="button"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    setEnrollment(null);
                    setPassword("");
                    setCode("");
                  }}
                >
                  Cancel setup
                </Button>
              )}
            </div>
          )}
        </form>
      )}
    </section>
  );
}

function deviceName(label: string) {
  if (/iPhone/i.test(label)) return "iPhone";
  if (/iPad/i.test(label)) return "iPad";
  if (/Android/i.test(label)) return "Android browser";
  if (/Windows/i.test(label)) return "Windows browser";
  if (/Macintosh|Mac OS/i.test(label)) return "Mac browser";
  if (/Linux/i.test(label)) return "Linux browser";
  return label || "Browser";
}

function Devices() {
  const cache = useQueryClient();
  const { signOut } = useAccount();
  const devices = useQuery({
    queryKey: ["account-devices"],
    queryFn: () => api<Device[]>("/account/devices"),
  });
  const revoke = useMutation({
    mutationFn: (device: Device) =>
      api(`/account/devices/${device.id}`, { method: "DELETE" }),
    onSuccess: (_result, device) => {
      if (device.current) void signOut?.();
      else void cache.invalidateQueries({ queryKey: ["account-devices"] });
    },
  });
  return (
    <section className="panel account-settings-card">
      <h2>Signed-in devices</h2>
      <p className="muted">
        Sign out a device without interrupting your other sessions.
      </p>
      <ErrorNotice error={devices.error ?? revoke.error} />
      {devices.isPending ? (
        <Loading />
      ) : (
        <ul className="account-device-list">
          {devices.data?.map((device) => (
            <li key={device.id}>
              <div>
                <strong>{deviceName(device.label)}</strong>
                {device.current && (
                  <span className="account-current-device">This device</span>
                )}
                <p>
                  Last active {new Date(device.last_seen_at).toLocaleString()}
                </p>
              </div>
              <Button
                variant="secondary"
                disabled={revoke.isPending}
                onClick={() => revoke.mutate(device)}
                aria-label={`Sign out ${deviceName(device.label)}${device.current ? " (this device)" : ""}`}
              >
                Sign out
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function AccountSecurity() {
  const { user } = useAccount();
  return (
    <div className="account-security">
      <div className="account-profile-summary">
        <div className="account-avatar">
          {user?.username.slice(0, 1).toUpperCase()}
        </div>
        <div>
          <h2>{user?.display_name || user?.username}</h2>
          <p className="muted">
            {user?.username} · {user?.is_admin ? "Administrator" : "Member"}
          </p>
        </div>
      </div>
      <div className="account-security-grid">
        <PasswordSettings />
        <TwoFactorSettings />
      </div>
      <Devices />
    </div>
  );
}
