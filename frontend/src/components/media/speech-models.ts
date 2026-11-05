import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";

export type SpeechModelChoice = {
  id: string;
  name: string;
  available: boolean;
};

export function useSpeechModels(enabled = true) {
  return useQuery({
    queryKey: ["speech-models"],
    enabled,
    queryFn: () => api<{ items?: SpeechModelChoice[] }>("/audio/models"),
  });
}
