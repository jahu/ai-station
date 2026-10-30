// Browser drafts are account-scoped and removed at sign-out/account switches.
// No password, authenticator secret, recovery code or bearer token is persisted.
let owner: string | null = null;
let epoch = 0;
const listeners = new Set<() => void>();

export function subscribeStorageAccount(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export const accountEpoch = () => epoch;
export const activeStorageAccount = () => owner;
export const accountStorageKey = (key: string) =>
  owner ? `ai-station:user:${owner}:${key}` : key;

export function clearPrivateBrowserState() {
  epoch += 1;
  for (const name of ["sessionStorage", "localStorage"] as const) {
    try {
      const storage = window[name];
      for (const key of Object.keys(storage)) {
        if (key.startsWith("ai-station:") && key !== "ai-station:auth-event")
          storage.removeItem(key);
      }
    } catch {
      // Private browsing/quota restrictions must not prevent signing out.
    }
  }
  if (owner !== null) {
    owner = null;
    listeners.forEach((listener) => listener());
  }
}

export function activateStorageAccount(id: string) {
  if (owner !== id) {
    clearPrivateBrowserState();
    owner = id;
    listeners.forEach((listener) => listener());
  }
}

export function announceAccountChange() {
  try {
    localStorage.setItem(
      "ai-station:auth-event",
      `${Date.now()}-${Math.random()}`,
    );
  } catch {
    // The server cookie remains authoritative when browser storage is blocked.
  }
}
