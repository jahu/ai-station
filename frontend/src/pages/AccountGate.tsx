import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Eye, EyeOff, LockKeyhole, Sparkles } from "lucide-react";
import { api, ApiError } from "../api";
import { AccountContext, type AccountStatus } from "../account-context";
import {
  activateStorageAccount,
  activeStorageAccount,
  subscribeStorageAccount,
  announceAccountChange,
  clearPrivateBrowserState,
} from "../lib/account-storage";
import { Button } from "../components/ui/button";
import { ErrorNotice, Loading } from "../components/common";
import OperatorGate from "./OperatorLogin";

const KEY = ["account-auth"];
const json = (body: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const signedOut: AccountStatus = {
  authenticated: false,
  setup_required: false,
  user: null,
};

function initialSetupToken() {
  const marker = window.location.hash.indexOf("?");
  return marker < 0
    ? null
    : new URLSearchParams(window.location.hash.slice(marker + 1)).get(
        "setup_token",
      );
}

function clearSetupFragment() {
  const marker = window.location.hash.indexOf("?");
  if (marker < 0) return;
  const params = new URLSearchParams(window.location.hash.slice(marker + 1));
  if (!params.has("setup_token")) return;
  params.delete("setup_token");
  const url = new URL(window.location.href);
  url.hash =
    window.location.hash.slice(0, marker) +
    (params.size ? "?" + params.toString() : "");
  window.history.replaceState(window.history.state, "", url);
}

function Credentials({
  setup,
  setupLinkRequired,
  localSetupToken,
  busy,
  error,
  onAuthenticated,
}: {
  setup: boolean;
  setupLinkRequired: boolean;
  localSetupToken: string | null;
  busy: boolean;
  error: Error | null;
  onAuthenticated: (status: AccountStatus) => void;
}) {
  const [username, setUsername] = useState(setup ? "admin" : "");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [factor, setFactor] = useState("");
  const [needsFactor, setNeedsFactor] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [visible, setVisible] = useState(false);
  const [validation, setValidation] = useState<Error | null>(null);
  const submit = useMutation({
    gcTime: 0,
    mutationFn: () =>
      api<AccountStatus>(
        setup ? "/auth/setup" : "/auth/login",
        json({
          username,
          password,
          ...(setup && localSetupToken
            ? { local_setup_token: localSetupToken }
            : {}),
          ...(!setup && factor ? { second_factor: factor } : {}),
          ...(!setup && rememberMe ? { remember_me: true } : {}),
        }),
      ),
    onSuccess: (status) => {
      setPassword("");
      setConfirmation("");
      setFactor("");
      onAuthenticated(status);
    },
    onError: (cause) => {
      if (
        cause instanceof ApiError &&
        cause.status === 403 &&
        /verification|code/i.test(cause.message)
      )
        setNeedsFactor(true);
    },
  });
  const pending = busy || submit.isPending;
  const needsLocalLink = setup && setupLinkRequired && !localSetupToken;
  return (
    <main id="main" tabIndex={-1} className="account-entry">
      <div className="account-entry-brand">
        <span className="brand-symbol">
          <Sparkles size={21} />
        </span>
        <strong>AI Station</strong>
      </div>
      <section className="account-entry-card" aria-labelledby="account-heading">
        <div className="account-entry-icon">
          <LockKeyhole size={23} />
        </div>
        <div className="eyebrow">YOUR PERSONAL AI WORKSTATION</div>
        <h1 id="account-heading">
          {setup ? "Make this station yours." : "Welcome back."}
        </h1>
        <p className="account-entry-intro">
          {setup
            ? "Create your administrator account. You can add other users after setup."
            : "Sign in to your private conversations, creations and agents."}
        </p>
        <ErrorNotice error={validation ?? submit.error ?? error} />
        {needsLocalLink && (
          <p className="notice">
            Open the private setup link shown when AI Station starts on this
            computer. It lets you create the first account securely.
          </p>
        )}
        <form
          className="account-form"
          onSubmit={(event) => {
            event.preventDefault();
            setValidation(null);
            if (setup && password !== confirmation) {
              setValidation(new Error("Passwords do not match."));
              return;
            }
            if (!pending && !needsLocalLink) submit.mutate();
          }}
        >
          <label>
            Username
            <input
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              minLength={2}
              maxLength={64}
              required
              disabled={pending || needsLocalLink}
              autoFocus
            />
          </label>
          <label>
            Password
            <span className="account-password-input">
              <input
                type={visible ? "text" : "password"}
                autoComplete={setup ? "new-password" : "current-password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={setup ? 12 : 1}
                maxLength={200}
                required
                disabled={pending || needsLocalLink}
              />
              <button
                type="button"
                className="icon-button"
                aria-label={visible ? "Hide password" : "Show password"}
                onClick={() => setVisible(!visible)}
              >
                {visible ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </span>
          </label>
          {setup && (
            <>
              <p className="account-field-hint">
                At least 12 characters. Use a unique password.
              </p>
              <label>
                Confirm password
                <input
                  type={visible ? "text" : "password"}
                  autoComplete="new-password"
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  minLength={12}
                  maxLength={200}
                  required
                  disabled={pending || needsLocalLink}
                />
              </label>
            </>
          )}
          {needsFactor && (
            <label>
              Authenticator or recovery code
              <input
                autoComplete="one-time-code"
                value={factor}
                onChange={(event) => setFactor(event.target.value)}
                maxLength={64}
                required
                disabled={pending}
                autoFocus
              />
              <span className="account-field-hint">
                Enter a fresh code from your authenticator, or one unused
                recovery code.
              </span>
            </label>
          )}
          {!setup && (
            <label className="account-remember">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(event) => setRememberMe(event.target.checked)}
                disabled={pending}
              />
              <span>
                <strong>Keep me logged in</strong>
                <small>Stay signed in for 30 days on this device.</small>
              </span>
            </label>
          )}
          <Button
            type="submit"
            disabled={
              pending || needsLocalLink || username.length < 2 || !password
            }
          >
            {pending
              ? "Please wait…"
              : setup
                ? "Create your account"
                : "Sign in"}
            <ArrowRight size={16} />
          </Button>
        </form>
        {!setup && (
          <p className="account-owner-hint">
            Upgrading from operator access? Use <strong>admin</strong> and your
            existing password.
          </p>
        )}
        <div className="account-entry-footer">
          <LockKeyhole size={13} />
          <span>Your workspace stays on this station.</span>
        </div>
      </section>
    </main>
  );
}

export default function AccountGate({ children }: { children: ReactNode }) {
  const cache = useQueryClient();
  const [localSetupToken, setLocalSetupToken] = useState(initialSetupToken);
  useEffect(() => {
    function receiveSetupLink() {
      const value = initialSetupToken();
      if (value) setLocalSetupToken(value);
      clearSetupFragment();
    }
    receiveSetupLink();
    window.addEventListener("hashchange", receiveSetupLink);
    return () => window.removeEventListener("hashchange", receiveSetupLink);
  }, []);
  const [locked, setLocked] = useState(false);
  const [closing, setClosing] = useState(false);
  const prepared = useSyncExternalStore(
    subscribeStorageAccount,
    activeStorageAccount,
    () => null,
  );
  const [logoutError, setLogoutError] = useState<Error | null>(null);
  const status = useQuery({
    queryKey: KEY,
    retry: false,
    queryFn: async () => {
      try {
        return await api<AccountStatus>("/auth");
      } catch (error) {
        if (error instanceof ApiError && [404, 410].includes(error.status))
          return null;
        throw error;
      }
    },
  });
  const purge = useCallback(() => {
    clearPrivateBrowserState();
    void cache.cancelQueries();
    cache.removeQueries({ predicate: (query) => query.queryKey[0] !== KEY[0] });
    cache.getMutationCache().clear();
  }, [cache]);
  const authenticated = useCallback(
    (value: AccountStatus) => {
      setLocalSetupToken(null);
      purge();
      cache.setQueryData(KEY, value);
      setLocked(false);
      setLogoutError(null);
      announceAccountChange();
    },
    [cache, purge],
  );
  const signOut = useCallback(async () => {
    const owner = activeStorageAccount();
    setLocked(true);
    setClosing(true);
    setLogoutError(null);
    purge();
    cache.setQueryData(KEY, signedOut);
    announceAccountChange();
    try {
      await api("/auth/logout", {
        ...json({}),
        headers: {
          "Content-Type": "application/json",
          ...(owner ? { "X-AI-Station-Account": owner } : {}),
        },
      });
    } catch (error) {
      setLogoutError(
        error instanceof Error
          ? error
          : new Error("Could not confirm sign-out. Try again."),
      );
    } finally {
      setClosing(false);
    }
  }, [cache, purge]);
  const userId =
    !locked && status.data?.authenticated ? status.data.user?.id : null;
  const accountProfileActive = status.data != null;
  useLayoutEffect(() => {
    if (userId && prepared !== userId) {
      purge();
      activateStorageAccount(userId);
    } else if (!userId && prepared !== null) {
      purge();
    }
  }, [userId, prepared, purge]);
  useEffect(() => {
    if (!accountProfileActive) return;
    const expired = () => {
      setLocked(true);
      purge();
      cache.setQueryData(KEY, signedOut);
    };
    const switched = (event: StorageEvent) => {
      if (event.key !== "ai-station:auth-event" || !event.newValue) return;
      expired();
      void api<AccountStatus>("/auth")
        .then((value) => {
          cache.setQueryData(KEY, value);
          setLocked(false);
        })
        .catch(() => {});
    };
    window.addEventListener("ai-station:session-expired", expired);
    window.addEventListener("storage", switched);
    return () => {
      window.removeEventListener("ai-station:session-expired", expired);
      window.removeEventListener("storage", switched);
    };
  }, [accountProfileActive, cache, purge]);
  if (status.isPending) return <Loading />;
  if (status.error)
    return (
      <main className="account-entry">
        <section className="account-entry-card">
          <h1>Reconnect to your station.</h1>
          <ErrorNotice error={status.error} />
          <Button onClick={() => void status.refetch()}>Try again</Button>
        </section>
      </main>
    );
  if (status.data === null) return <OperatorGate>{children}</OperatorGate>;
  if (!userId || !status.data?.user)
    return (
      <Credentials
        setup={status.data?.setup_required ?? false}
        setupLinkRequired={status.data?.setup_link_required ?? false}
        localSetupToken={localSetupToken}
        busy={closing}
        error={logoutError}
        onAuthenticated={authenticated}
      />
    );
  if (prepared !== userId) return <Loading />;
  return (
    <AccountContext.Provider
      value={{ mode: "accounts", user: status.data.user, signOut }}
    >
      <div key={userId} className="account-workspace">
        {children}
      </div>
    </AccountContext.Provider>
  );
}
