import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, ImagePlus, Library, Upload, X } from "lucide-react";
import { api, type Artifact } from "../../api";
import { ErrorNotice } from "../common";
import { Button } from "../ui/button";

type Props = {
  kind: "image" | "audio";
  label: string;
  hint: string;
  value: string;
  onChange: (id: string) => void;
  disabled: boolean;
  onBusy: (busy: boolean) => void;
};
export default function MediaInput({
  kind,
  label,
  hint,
  value,
  onChange,
  disabled,
  onBusy,
}: Props) {
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [dragging, setDragging] = useState(false);
  const cache = useQueryClient();
  const source = useQuery({
    queryKey: ["artifact", value],
    queryFn: () => api<Artifact>(`/artifacts/${value}`),
    enabled: !!value,
  });
  const library = useQuery({
    queryKey: ["media-inputs"],
    queryFn: () => api<Artifact[]>("/artifacts"),
    enabled: libraryOpen,
  });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return api<Artifact>(
        kind === "image" ? "/images/uploads" : "/audio/uploads",
        { method: "POST", body },
      );
    },
    onMutate: () => onBusy(true),
    onSuccess: (artifact) => {
      cache.setQueryData(["artifact", artifact.id], artifact);
      onChange(artifact.id);
      void cache.invalidateQueries({ queryKey: ["media-inputs"] });
    },
    onSettled: () => onBusy(false),
  });
  const Icon = kind === "image" ? ImagePlus : AudioLines;
  const available = library.data?.filter(
    (a) =>
      a.type === kind &&
      (kind !== "image" || ["image/png", "image/jpeg"].includes(a.mime_type)) &&
      (kind !== "audio" || a.mime_type === "audio/wav") &&
      `${a.title ?? ""} ${a.original_filename}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <div className="media-input">
      <div className="media-field-heading">
        <span>{label}</span>
        {value && (
          <button
            type="button"
            className="icon-button"
            aria-label={`Remove ${label.toLowerCase()}`}
            disabled={disabled}
            onClick={() => onChange("")}
          >
            <X size={15} />
          </button>
        )}
      </div>
      {value ? (
        <div className={`media-source media-source-${kind}`}>
          {kind === "image" ? (
            <img
              src={`/api/artifacts/${value}/thumbnail`}
              alt="Portrait preview"
            />
          ) : (
            <>
              <AudioLines size={23} />
              <audio
                controls
                preload="metadata"
                src={`/api/artifacts/${value}/file`}
                aria-label={`${label} preview`}
              />
            </>
          )}
          <span title={source.data?.original_filename}>
            {source.data?.title ||
              source.data?.original_filename ||
              "Loading reference…"}
          </span>
        </div>
      ) : (
        <label
          className={`media-upload ${dragging ? "is-dragging" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            if (!disabled) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            const file = event.dataTransfer.files[0];
            if (file && !disabled) upload.mutate(file);
          }}
        >
          <Icon size={27} />
          <strong>
            {upload.isPending
              ? "Uploading…"
              : kind === "image"
                ? "Drop a portrait here"
                : "Drop a voice recording here"}
          </strong>
          <span>{hint}</span>
          <span className="media-browse">
            <Upload size={13} /> Browse files
          </span>
          <input
            className="sr-only"
            type="file"
            aria-label={kind === "image" ? "Upload portrait" : "Upload speech"}
            accept={
              kind === "image" ? "image/png,image/jpeg" : "audio/wav,.wav"
            }
            disabled={disabled}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) upload.mutate(file);
            }}
          />
        </label>
      )}
      <Button
        type="button"
        variant="ghost"
        className="media-library-toggle"
        disabled={disabled}
        aria-expanded={libraryOpen}
        onClick={() => setLibraryOpen(!libraryOpen)}
      >
        <Library size={14} />
        {libraryOpen ? "Close Library" : "Choose from Library"}
      </Button>
      {libraryOpen && (
        <div
          className="media-picker"
          role="region"
          aria-label={`${label} library`}
        >
          <label>
            <span className="sr-only">Search {label.toLowerCase()}</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search filenames…"
            />
          </label>
          {library.isPending ? (
            <p className="muted">Loading your Library…</p>
          ) : !available?.length ? (
            <p className="muted">
              No matching {kind === "image" ? "portraits" : "WAV recordings"}.
              Upload one above.
            </p>
          ) : (
            <div className="media-picker-list">
              {available.map((a) => (
                <button
                  type="button"
                  key={a.id}
                  disabled={disabled}
                  onClick={() => {
                    cache.setQueryData(["artifact", a.id], a);
                    onChange(a.id);
                    setLibraryOpen(false);
                  }}
                >
                  {kind === "image" ? (
                    <img src={`/api/artifacts/${a.id}/thumbnail`} alt="" />
                  ) : (
                    <AudioLines size={18} />
                  )}
                  <span>{a.title || a.original_filename}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      <ErrorNotice error={upload.error ?? source.error ?? library.error} />
    </div>
  );
}
