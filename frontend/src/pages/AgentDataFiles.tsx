import { useId, useRef } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Upload, X } from "lucide-react";
import { api, type Artifact } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import LibraryPicker from "../components/media/LibraryPicker";

export type DataScope = { input_artifact_ids: string[]; max_repairs: number };
export default function AgentDataFiles({
  value,
  disabled,
  onChange,
}: {
  value?: DataScope | null;
  disabled: boolean;
  onChange: (value: DataScope) => void;
}) {
  const id = useId();
  const file = useRef<HTMLInputElement>(null);
  const cache = useQueryClient();
  const ids = value?.input_artifact_ids ?? [];
  const files = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["artifact", id],
      queryFn: () => api<Artifact>(`/artifacts/${id}`),
    })),
  });
  const updateIds = (next: string[]) =>
    onChange({
      input_artifact_ids: next,
      max_repairs: value?.max_repairs ?? 1,
    });
  const upload = useMutation({
    mutationFn: async (selected: File[]) => {
      if (selected.length + ids.length > 8)
        throw new Error("Choose up to eight data files.");
      if (selected.some((item) => item.size > 16 * 1024 * 1024))
        throw new Error("Each file may be up to 16 MB.");
      const added: Artifact[] = [];
      try {
        for (const item of selected) {
          const body = new FormData();
          body.append("file", item);
          const artifact = await api<Artifact>("/data/uploads", {
            method: "POST",
            body,
          });
          added.push(artifact);
          cache.setQueryData(["artifact", artifact.id], artifact);
        }
      } finally {
        // One definition update per batch, including partial success. Conversation
        // drafts autosave this callback with a version guard.
        if (added.length) updateIds([...ids, ...added.map((item) => item.id)]);
      }
      return added;
    },
    onSettled: () => {
      void cache.invalidateQueries({ queryKey: ["library"] });
    },
  });
  const busy = disabled || upload.isPending;
  return (
    <section className="agent-data-files" aria-labelledby={id}>
      <h3 id={id}>Data to analyse</h3>
      <p className="muted">
        Choose CSV or Excel files. Originals stay unchanged; analysis runs
        locally with no internet access.
      </p>
      <div className="row agent-data-actions">
        <input
          ref={file}
          type="file"
          accept=".csv,.xlsx"
          multiple
          hidden
          tabIndex={-1}
          aria-label="Upload agent data"
          disabled={busy || ids.length >= 8}
          onChange={(event) => {
            const selected = Array.from(event.target.files ?? []);
            event.target.value = "";
            if (selected.length) upload.mutate(selected);
          }}
        />
        <Button
          type="button"
          variant="secondary"
          disabled={busy || ids.length >= 8}
          onClick={() => file.current?.click()}
        >
          <Upload size={15} />
          {upload.isPending ? "Uploading…" : "Upload CSV / Excel"}
        </Button>
        <LibraryPicker
          kind="document"
          existing={ids}
          limit={8 - ids.length}
          busy={busy}
          onSelect={(items) => updateIds([...ids, ...items.map((a) => a.id)])}
        />
      </div>
      <ErrorNotice
        error={upload.error ?? files.find((item) => item.error)?.error ?? null}
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
              </span>
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
                onClick={() => updateIds(ids.filter((item) => item !== aid))}
              >
                <X size={16} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No files selected yet.</p>
      )}
      <label>
        Automatic fixes
        <select
          aria-label="Automatic fixes"
          disabled={busy || !ids.length}
          value={value?.max_repairs ?? 1}
          onChange={(event) =>
            onChange({
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
        Fixes apply only to confirmed code or output errors, within the agent’s
        time limit.
      </p>
    </section>
  );
}
