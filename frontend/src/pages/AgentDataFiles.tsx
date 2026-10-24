import DataOperation from "./DataOperation";
import { uploadDataFiles } from "./data-upload";
import { useEffect, useId, useRef } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Upload, X } from "lucide-react";
import { useDataInputs } from "./useDataInputs";
import { api, type Artifact, type Run } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import LibraryPicker from "../components/media/LibraryPicker";

export type DataScope = {
  input_artifact_ids: string[];
  max_repairs: number;
  operation?: "analyze" | "create";
};
export default function AgentDataFiles({
  value,
  disabled,
  onChange,
  showInspection = false,
  onUploading,
  allowResearch = false,
  allowMemory = false,
  showRepairSettings = true,
  showOperation = true,
}: {
  value?: DataScope | null;
  disabled: boolean;
  onChange: (value: DataScope) => void;
  showInspection?: boolean;
  allowResearch?: boolean;
  allowMemory?: boolean;
  showRepairSettings?: boolean;
  showOperation?: boolean;
  onUploading?: (busy: boolean) => void;
}) {
  const id = useId();
  const file = useRef<HTMLInputElement>(null);
  const cache = useQueryClient();
  const ids = value?.input_artifact_ids ?? [];
  const creating = value?.operation === "create";
  const hasContext = allowResearch || allowMemory;
  const maxFiles = hasContext ? 7 : 8;
  const files = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["artifact", id],
      queryFn: () => api<Artifact>(`/artifacts/${id}`),
    })),
  });
  const inspection = useDataInputs(showInspection ? value : null);
  const inspect = useMutation({
    mutationFn: (artifact_id: string) =>
      api<Run>("/data/inspections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artifact_id }),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["artifact"] });
    },
  });
  const updateIds = (next: string[]) =>
    onChange({
      ...value,
      input_artifact_ids: next,
      max_repairs: value?.max_repairs ?? 1,
    });
  const upload = useMutation({
    mutationFn: async (selected: File[]) => {
      if (hasContext && ids.length + selected.length > maxFiles)
        throw new Error(
          allowMemory
            ? "Choose at most seven files when using saved memory context."
            : "Choose at most seven files when using public research sources.",
        );
      return uploadDataFiles(
        selected,
        cache,
        (added) => updateIds([...ids, ...added.map((item) => item.id)]),
        ids.length,
        files.reduce((bytes, file) => bytes + (file.data?.size_bytes ?? 0), 0),
      );
    },
  });
  useEffect(() => {
    onUploading?.(upload.isPending);
  }, [upload.isPending, onUploading]);
  const busy = disabled || upload.isPending || inspect.isPending;
  return (
    <section className="agent-data-files" aria-labelledby={id}>
      <h3 id={id}>{creating ? "Create files" : "Data to analyse"}</h3>
      {showOperation && (
        <DataOperation
          value={value}
          disabled={busy}
          hasResearch={hasContext}
          onChange={onChange}
        />
      )}
      <p className="muted">
        {creating
          ? "Describe the files and their contents in the instruction. No input files are read."
          : allowMemory
            ? "Scoped saved memory is available to this analysis. CSV, Excel or JSON files are optional (up to seven)."
            : allowResearch
              ? "Reviewed public sources are available to this analysis. CSV, Excel or JSON files are optional (up to seven)."
              : "Choose CSV, Excel or JSON files."}{" "}
        Originals stay unchanged; Python runs locally with no internet access.
      </p>
      {ids.length > maxFiles && (
        <p className="notice" role="alert">
          Selected context uses one input slot. Remove a file to keep at most
          seven data files.
        </p>
      )}
      {!creating && (
        <>
          <div className="row agent-data-actions">
            <input
              ref={file}
              type="file"
              accept=".csv,.xlsx,.json"
              multiple
              hidden
              tabIndex={-1}
              aria-label="Upload agent data"
              disabled={busy || ids.length >= maxFiles}
              onChange={(event) => {
                const selected = Array.from(event.target.files ?? []);
                event.target.value = "";
                if (selected.length) upload.mutate(selected);
              }}
            />
            <Button
              type="button"
              variant="secondary"
              disabled={busy || ids.length >= maxFiles}
              onClick={() => file.current?.click()}
            >
              <Upload size={15} />
              {upload.isPending ? "Uploading…" : "Upload data"}
            </Button>
            <LibraryPicker
              kind="document"
              existing={ids}
              limit={Math.max(0, maxFiles - ids.length)}
              busy={busy}
              onSelect={(items) =>
                updateIds([...ids, ...items.map((a) => a.id)])
              }
            />
          </div>
          <ErrorNotice
            error={
              upload.error ??
              inspect.error ??
              files.find((item) => item.error)?.error ??
              inspection.states.find((item) => item.error)?.error ??
              null
            }
          />
          {ids.length ? (
            <ul className="agent-data-inputs">
              {ids.map((aid, index) => (
                <li key={aid}>
                  <FileSpreadsheet size={18} aria-hidden="true" />
                  <span>
                    {files[index]?.data?.title ||
                      files[index]?.data?.original_filename ||
                      "Loading data file…"}
                    {files[index]?.data?.metadata.agent_data_research ===
                      true && (
                      <small className="muted">
                        Captured public data · original sources are not
                        refreshed
                      </small>
                    )}
                    {showInspection && (
                      <small className="muted" role="status">
                        {inspection.states[index]?.label}
                      </small>
                    )}
                  </span>
                  {showInspection &&
                    inspection.states[index]?.file &&
                    (!inspection.states[index]?.file?.metadata
                      ?.data_inspection_run_id ||
                      ["failed", "canceled", "interrupted"].includes(
                        inspection.states[index]?.run?.status ?? "",
                      )) && (
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={busy}
                        onClick={() => inspect.mutate(aid)}
                      >
                        Inspect file
                      </Button>
                    )}
                  <Link
                    to={`/library/${aid}`}
                    aria-label={`Preview data file ${index + 1}`}
                  >
                    Preview
                  </Link>
                  <button
                    className="icon-button"
                    type="button"
                    disabled={busy}
                    aria-label={`Remove data file ${index + 1}`}
                    onClick={() =>
                      updateIds(ids.filter((item) => item !== aid))
                    }
                  >
                    <X size={16} />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              {allowResearch
                ? "No files selected · use reviewed public sources."
                : "No files selected yet."}
            </p>
          )}
        </>
      )}
      {showRepairSettings && (
        <>
          <label>
            Automatic fixes
            <select
              aria-label="Automatic fixes"
              disabled={busy || (!creating && !allowResearch && !ids.length)}
              value={value?.max_repairs ?? 1}
              onChange={(event) =>
                onChange({
                  ...value,
                  input_artifact_ids: ids,
                  max_repairs: Number(event.target.value),
                })
              }
            >
              <option value={0}>Off</option>
              <option value={1}>One attempt</option>
              <option value={2}>Two attempts</option>
            </select>
          </label>
          <p className="muted">
            Fixes apply only to confirmed code or output errors, within the
            execution time limit.
          </p>
        </>
      )}
    </section>
  );
}
