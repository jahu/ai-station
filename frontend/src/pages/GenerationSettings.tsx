import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";
import UnifiedModelPicker from "./UnifiedModelPicker";

export type GenerationPreferences = {
  revision: number;
  enabled: boolean;
  model: string;
  target_language: "en";
};

export default function GenerationSettings() {
  const cache = useQueryClient();
  const preferences = useQuery({
    queryKey: ["generation-preferences"],
    queryFn: () => api<GenerationPreferences>("/generation/preferences"),
  });
  const [draft, setDraft] = useState<GenerationPreferences | null>(null);
  const [saved, setSaved] = useState(false);
  const values = draft ?? preferences.data;
  const save = useMutation({
    mutationFn: () =>
      api<GenerationPreferences>("/generation/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      }),
    onSuccess: (result) => {
      cache.setQueryData(["generation-preferences"], result);
      setDraft(null);
      setSaved(true);
    },
  });
  if (!values)
    return (
      <>
        <Loading />
        <ErrorNotice error={preferences.error} />
      </>
    );
  return (
    <section
      className="panel settings-general settings-generation"
      aria-label="Generation settings"
    >
      <div>
        <h2>Write naturally. Keep control.</h2>
      </div>
      <p className="muted">
        Optionally translate image, video and music descriptions to English with
        a local LLM before generation. Your original wording stays available.
        Quoted text and model tokens are preserved.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!save.isPending) save.mutate();
        }}
      >
        <label className="generation-toggle">
          <input
            type="checkbox"
            role="switch"
            checked={values.enabled}
            disabled={save.isPending}
            onChange={(event) => {
              setDraft({ ...values, enabled: event.target.checked });
              setSaved(false);
            }}
          />
          <span>
            <strong>Translate media prompts</strong>
            <small>
              Images, Video and music descriptions, including media actions in
              Chat/Work. Speech, lyrics and ordinary conversations stay in their
              original language.
            </small>
          </span>
        </label>
        <details className="generation-advanced" open={!values.model}>
          <summary>Translator and language</summary>
          <p className="muted">
            Choose an installed llama.cpp model or your configured local server.
            Managed llama.cpp models load when needed and use automatic GPU
            handoff. Translation finishes before generation; existing external
            model servers remain under your control and are never stopped.
          </p>
          <UnifiedModelPicker
            allowedProvider="local-openai-compatible"
            providerKey="local-openai-compatible"
            modelKey={values.model}
            location="local"
            busy={save.isPending}
            onSelect={(choice) => {
              setDraft({ ...values, model: choice.model_key });
              setSaved(false);
            }}
          />
          <p className="muted">Target language: English.</p>
        </details>
        {values.enabled && !values.model && (
          <p role="status">
            Choose a local translator before enabling translation.
          </p>
        )}
        <ErrorNotice error={preferences.error ?? save.error} />
        <div className="row">
          <Button
            type="submit"
            disabled={save.isPending || (values.enabled && !values.model)}
          >
            {save.isPending ? "Saving…" : "Save generation settings"}
          </Button>
          {save.error && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setDraft(null);
                void preferences.refetch();
              }}
            >
              Reload settings
            </Button>
          )}
          {saved && <span role="status">Generation settings saved.</span>}
        </div>
      </form>
    </section>
  );
}
