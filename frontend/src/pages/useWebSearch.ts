import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";

export type ChatPreferences = {
  version: number;
  mode: "assistant" | "chat" | "work";
  provider: string;
  model: string;
  send_key: "enter" | "ctrl-enter";
  web_search_enabled: boolean;
};

export function useWebSearch(defaultAllowed: boolean) {
  const cache = useQueryClient();
  const preferences = useQuery({
    queryKey: ["chat-preferences"],
    queryFn: () => api<ChatPreferences>("/chat/preferences"),
  });
  const [override, setEnabled] = useState<boolean | null>(null);
  const [renderPages, setRenderPages] = useState(false);
  const save = useMutation({
    mutationFn: async (enabled: boolean) => {
      const current = await api<ChatPreferences>("/chat/preferences");
      return api<ChatPreferences>("/chat/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...current, web_search_enabled: enabled }),
      });
    },
    onSuccess: (result) => cache.setQueryData(["chat-preferences"], result),
  });
  return {
    enabled:
      override ??
      (defaultAllowed && (preferences.data?.web_search_enabled ?? true)),
    setEnabled,
    renderPages,
    setRenderPages,
    onToggle: (enabled: boolean) => {
      setEnabled(enabled);
      if (!enabled) setRenderPages(false);
      save.mutate(enabled);
    },
    busy: save.isPending,
    ready: !preferences.isPending && !preferences.isError,
    error: save.error ?? preferences.error,
  };
}
