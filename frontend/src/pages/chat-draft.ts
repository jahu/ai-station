import { useRef, useState } from "react";

const prefix = "ai-station:chat-draft:";
const maxCharacters = 32000;

function read(scope: string) {
  try {
    const value = sessionStorage.getItem(prefix + scope);
    return value && value.length <= maxCharacters ? value : "";
  } catch {
    return "";
  }
}

export function clearChatDraft(scope: string) {
  try {
    sessionStorage.removeItem(prefix + scope);
  } catch {
    // Storage may be disabled; the composer continues to work in memory.
  }
}

export function useChatDraft(scope: string) {
  const [value, setValue] = useState(() => read(scope));
  const current = useRef(value);
  const [restored, setRestored] = useState(() => !!read(scope));
  const update = (text: string) => {
    const next = text.slice(0, maxCharacters);
    current.current = next;
    setValue(next);
    setRestored(false);
    try {
      if (next) sessionStorage.setItem(prefix + scope, next);
      else clearChatDraft(scope);
    } catch {
      // Quota/private-browser failures must never prevent typing or Send.
    }
  };
  return {
    value,
    update,
    restored,
    accept: (submitted: string) => {
      if (current.current === submitted) update("");
    },
  };
}

const requestPrefix = "ai-station:chat-request:";

export async function chatRequestId(scope: string, body: string) {
  if (!crypto.subtle) return crypto.randomUUID();
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(body),
  );
  const hash = Array.from(new Uint8Array(bytes), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  let id = crypto.randomUUID();
  try {
    const previous = JSON.parse(
      sessionStorage.getItem(requestPrefix + scope) || "null",
    );
    if (
      previous?.hash === hash &&
      typeof previous.id === "string" &&
      /^[0-9a-f-]{36}$/.test(previous.id)
    )
      id = previous.id;
    sessionStorage.setItem(requestPrefix + scope, JSON.stringify({ hash, id }));
  } catch {
    // Existing in-memory identity remains the fallback when storage is blocked.
  }
  return id;
}

export function clearChatRequest(scope: string) {
  try {
    sessionStorage.removeItem(requestPrefix + scope);
  } catch {
    /* unavailable storage */
  }
}
