import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { Catalog } from "./UnifiedModelPicker";

export function useThinking(model: string, allowed: boolean, maxTokens = 2048) {
  const [requestedModel, setRequestedModel] = useState("");
  const catalog = useQuery({
    queryKey: ["chat-model-catalog"],
    queryFn: () => api<Catalog>("/chat/model-catalog"),
    staleTime: 30000,
  });
  const supported =
    catalog.data?.models?.find((item) => item.model_key === model)
      ?.reasoning_capability?.verified === true;
  const available = allowed && supported;
  const enabled = available && maxTokens >= 512 && requestedModel === model;
  return {
    available,
    enabled,
    blocked: maxTokens < 512,
    onChange: (value: boolean) => setRequestedModel(value ? model : ""),
  };
}
