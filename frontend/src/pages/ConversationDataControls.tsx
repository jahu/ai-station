import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import AgentDataFiles from "./AgentDataFiles";
import type { ConversationDataScope } from "./useDataInputs";

export default function ConversationDataControls({
  value,
  disabled,
  onChange,
  onUploading,
}: {
  value?: ConversationDataScope | null;
  disabled: boolean;
  onChange: (scope: ConversationDataScope) => void;
  onUploading: (busy: boolean) => void;
}) {
  const scope = value ?? { input_artifact_ids: [], max_repairs: 1 };
  const selectedUrls = scope.research?.fetch_urls.join("\n") ?? "";
  const [urlDraft, setUrlDraft] = useState({
    text: selectedUrls,
    selection: selectedUrls,
  });
  const displayedUrls =
    urlDraft.selection === selectedUrls ? urlDraft.text : selectedUrls;
  const catalog = useQuery({
    queryKey: ["llama-models"],
    queryFn: () =>
      api<{ models: { model_key: string; name: string }[] }>("/llama"),
    staleTime: 30000,
  });
  return (
    <section
      className="conversation-data-controls"
      aria-label="Local data analysis"
    >
      <AgentDataFiles
        value={scope}
        allowResearch={!!scope.research}
        disabled={disabled}
        showInspection
        onUploading={onUploading}
        onChange={(files) => onChange({ ...scope, ...files })}
      />
      <label className="check">
        <input
          type="checkbox"
          aria-label="Use public sources for analysis"
          disabled={disabled}
          checked={!!scope.research}
          onChange={(event) =>
            onChange({
              ...scope,
              research: event.target.checked
                ? { search_query: "", fetch_urls: [], read_search_pages: false }
                : undefined,
            })
          }
        />
        Use public sources for this analysis
      </label>
      {scope.research && (
        <div className="conversation-data-controls">
          <p className="muted">
            Review a public query or up to three URLs. Only these sources are
            read; Python stays offline. Files are optional.
          </p>
          <label>
            Public search query
            <input
              aria-label="Public data search query"
              maxLength={500}
              disabled={disabled}
              value={scope.research.search_query}
              onChange={(event) =>
                onChange({
                  ...scope,
                  research: {
                    ...scope.research!,
                    search_query: event.target.value,
                    read_search_pages:
                      !!event.target.value.trim() &&
                      scope.research!.read_search_pages,
                  },
                })
              }
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              aria-label="Read data search pages"
              disabled={disabled || !scope.research.search_query.trim()}
              checked={scope.research.read_search_pages}
              onChange={(event) =>
                onChange({
                  ...scope,
                  research: {
                    ...scope.research!,
                    read_search_pages: event.target.checked,
                  },
                })
              }
            />
            Read pages from search results
          </label>
          <label>
            Public URLs
            <textarea
              aria-label="Public data URLs"
              rows={2}
              disabled={disabled}
              placeholder="https://example.com/data.json"
              value={displayedUrls}
              onChange={(event) => {
                setUrlDraft({
                  text: event.target.value,
                  selection: event.target.value
                    .split(/\r?\n/)
                    .map((item) => item.trim())
                    .filter(Boolean)
                    .join("\n"),
                });
                onChange({
                  ...scope,
                  research: {
                    ...scope.research!,
                    fetch_urls: event.target.value
                      .split(/\r?\n/)
                      .map((value) => value.trim())
                      .filter(Boolean),
                  },
                });
              }}
            />
          </label>
        </div>
      )}
      <details>
        <summary>Analysis settings</summary>
        <label>
          Local analysis model
          <select
            aria-label="Local analysis model"
            value={scope.model ?? "auto"}
            disabled={disabled}
            onChange={(event) =>
              onChange({ ...scope, model: event.target.value })
            }
          >
            <option value="auto">Auto · choose a fitting local model</option>
            {(catalog.data?.models ?? [])
              .filter((model) => model.model_key.startsWith("llamacpp:"))
              .map((model) => (
                <option value={model.model_key} key={model.model_key}>
                  {model.name}
                </option>
              ))}
          </select>
        </label>
        <ErrorNotice error={catalog.error} />
        <label>
          Time limit
          <select
            aria-label="Analysis time limit"
            value={scope.maximum_runtime ?? 600}
            disabled={disabled}
            onChange={(event) =>
              onChange({
                ...scope,
                maximum_runtime: Number(event.target.value),
              })
            }
          >
            <option value={300}>5 minutes</option>
            <option value={600}>10 minutes</option>
            <option value={1800}>30 minutes</option>
            <option value={3600}>60 minutes</option>
          </select>
        </label>
      </details>
      <p className="muted">
        Your files stay on this station, even if the conversation uses an
        external model. Analysis may load a local model automatically.
      </p>
    </section>
  );
}
