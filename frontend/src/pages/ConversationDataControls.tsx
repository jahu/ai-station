import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import DataOperation from "./DataOperation";
import AgentDataFiles from "./AgentDataFiles";
import AgentDocuments from "./AgentDocuments";
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
      <p className="muted">
        For a reusable agent, ask “Create an agent…” with these inputs selected.
        Review its task and schedule before enabling it.
      </p>
      <DataOperation
        value={scope}
        disabled={disabled}
        hasResearch={!!scope.research || !!scope.documents}
        hasDocuments={!!scope.documents}
        onChange={(next) => onChange({ ...scope, ...next })}
      />
      {scope.operation === "create" ? (
        <p className="muted">
          Describe the workbook, table or chart in your message. Files are
          created locally from your instructions, without reading existing files
          or visiting websites.
        </p>
      ) : (
        <>
          <details
            className="conversation-data-files"
            open={scope.documents ? true : undefined}
          >
            <summary>
              PDF &amp; text documents
              {scope.documents
                ? ` · ${scope.documents.artifact_ids.length} selected`
                : " · optional"}
            </summary>
            <AgentDocuments
              context="analysis"
              value={scope.documents}
              disabled={disabled}
              onUploading={onUploading}
              onChange={(documents) => onChange({ ...scope, documents })}
            />
          </details>
          <label className="data-research-toggle">
            <input
              type="checkbox"
              aria-label="Use public sources for analysis"
              disabled={disabled}
              checked={!!scope.research}
              onChange={(event) =>
                onChange({
                  ...scope,
                  research: event.target.checked
                    ? {
                        search_query: "",
                        fetch_urls: [],
                        read_search_pages: false,
                      }
                    : undefined,
                })
              }
            />
            Use public sources for this analysis
          </label>
          {scope.research && (
            <div className="conversation-data-sources">
              <p className="muted">
                Review a public query or up to three URLs, one per line. Only
                these sources are read.
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
              {scope.research.search_query.trim() && (
                <label className="data-research-toggle">
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
              )}
              <label>
                Public URLs
                <textarea
                  aria-label="Public data URLs"
                  rows={2}
                  disabled={disabled}
                  placeholder="https://example.com/data.json"
                  value={displayedUrls}
                  onChange={(event) => {
                    const urls = event.target.value
                      .split(/\r?\n/)
                      .map((item) => item.trim())
                      .filter(Boolean);
                    setUrlDraft({
                      text: event.target.value,
                      selection: urls.join("\n"),
                    });
                    onChange({
                      ...scope,
                      research: {
                        ...scope.research!,
                        fetch_urls: urls,
                        ...(scope.research!.render_pages
                          ? { render_pages: urls.length > 0 ? true : undefined }
                          : {}),
                      },
                    });
                  }}
                />
              </label>
              {scope.research.fetch_urls.length > 0 && (
                <>
                  <label className="data-research-toggle">
                    <input
                      type="checkbox"
                      aria-label="Read data URLs with JavaScript"
                      disabled={disabled}
                      checked={scope.research.render_pages === true}
                      onChange={(event) =>
                        onChange({
                          ...scope,
                          research: {
                            ...scope.research!,
                            render_pages: event.target.checked
                              ? true
                              : undefined,
                          },
                        })
                      }
                    />
                    Read these pages with JavaScript
                  </label>
                  {scope.research.render_pages && (
                    <p className="muted">
                      Uses the local browser for these public URLs. Captured
                      text feeds the analysis; screenshots are saved for
                      inspection. Python stays offline.
                    </p>
                  )}
                </>
              )}
            </div>
          )}
        </>
      )}
      {scope.research || scope.documents ? (
        <details className="conversation-data-files">
          <summary>
            Add files · optional
            {scope.input_artifact_ids.length
              ? ` · ${scope.input_artifact_ids.length} selected`
              : ""}
          </summary>
          <AgentDataFiles
            value={scope}
            allowResearch={!!scope.research}
            allowDocuments={!!scope.documents}
            disabled={disabled}
            showInspection
            showOperation={false}
            showRepairSettings={false}
            onUploading={onUploading}
            onChange={(files) => onChange({ ...scope, ...files })}
          />
        </details>
      ) : (
        <>
          <AgentDataFiles
            value={scope}
            allowResearch={!!scope.research}
            allowDocuments={!!scope.documents}
            disabled={disabled}
            showInspection
            showOperation={false}
            showRepairSettings={false}
            onUploading={onUploading}
            onChange={(files) => onChange({ ...scope, ...files })}
          />
        </>
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
        <label>
          Automatic fixes
          <select
            aria-label="Automatic fixes"
            disabled={disabled}
            value={scope.max_repairs ?? 1}
            onChange={(event) =>
              onChange({ ...scope, max_repairs: Number(event.target.value) })
            }
          >
            <option value={0}>Off</option>
            <option value={1}>One attempt</option>
            <option value={2}>Two attempts</option>
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
        Analysis uses a local model. Your files stay on this station.
      </p>
    </section>
  );
}
