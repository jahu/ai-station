import {
  TRANSCRIPTION_AUDIO_TYPES,
  TRANSCRIPTION_AUDIO_ACCEPT,
} from "../../recording-formats";
import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Film, ImagePlus, Library, Upload, X } from "lucide-react";
import { api, type Artifact } from "../../api";
import { ErrorNotice } from "../common";
import { Button } from "../ui/button";
import { useListKeyboard } from "../../pages/useListKeyboard";

type Props = {
  kind: "image" | "audio" | "video";
  uploadEndpoint?: string;
  maxAudioSeconds?: number;
  audioMode?: "voice" | "transcription";
  label: string;
  hint: string;
  value: string;
  onChange: (id: string) => void;
  disabled: boolean;
  onBusy: (busy: boolean) => void;
};
export default function MediaInput({
  kind,
  uploadEndpoint,
  maxAudioSeconds = 60,
  audioMode = "voice",
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
        uploadEndpoint ??
          (kind === "image" ? "/images/uploads" : "/audio/uploads"),
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
  const Icon =
    kind === "image" ? ImagePlus : kind === "video" ? Film : AudioLines;
  const headingId = useId();
  const labelId = useId();
  const audioTypes =
    audioMode === "transcription" ? TRANSCRIPTION_AUDIO_TYPES : ["audio/wav"];
  const available =
    library.data?.filter(
      (a) =>
        a.type === kind &&
        (kind !== "image" ||
          ["image/png", "image/jpeg"].includes(a.mime_type)) &&
        (kind !== "video" ||
          (a.mime_type === "video/mp4" &&
            !!a.metadata?.frames &&
            [24, 25].includes(Number(a.metadata?.fps)))) &&
        (kind !== "audio" ||
          (a.metadata?.capability !== "audio.effects" &&
            audioTypes.includes(a.mime_type) &&
            (a.metadata?.duration_seconds === undefined ||
              a.metadata.duration_seconds <= maxAudioSeconds))) &&
        `${a.title ?? ""} ${a.original_filename}`
          .toLowerCase()
          .includes(search.toLowerCase()),
    ) ?? [];
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    available,
    (artifact) => artifact.id,
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
          ) : kind === "video" ? (
            <video
              controls
              preload="metadata"
              src={`/api/artifacts/${value}/file`}
              aria-label={`${label} preview`}
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
      ) : kind === "video" ? (
        <div className="media-upload">
          <Film size={27} />
          <strong>Choose your film</strong>
          <span>{hint}</span>
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
                ? "Drop an image here"
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
              kind === "image"
                ? "image/png,image/jpeg"
                : audioMode === "transcription"
                  ? TRANSCRIPTION_AUDIO_ACCEPT
                  : "audio/wav,.wav"
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
          ) : !available.length ? (
            <p className="muted">
              No matching{" "}
              {kind === "image"
                ? "portraits"
                : kind === "video"
                  ? "completed films"
                  : audioMode === "transcription"
                    ? "recordings"
                    : "WAV recordings"}
              .{" "}
              {kind === "video"
                ? "Create a film in Video, then choose it here."
                : "Upload one above."}
            </p>
          ) : (
            <section aria-labelledby={headingId}>
              <h3 id={headingId} className="sr-only">
                Reusable{" "}
                {kind === "image"
                  ? "portraits"
                  : kind === "video"
                    ? "films"
                    : "recordings"}
              </h3>
              <p id={labelId} className="dashboard-note">
                Arrow keys choose a file while the list is focused. Enter
                attaches it.
              </p>
              <div
                ref={listRef}
                className="media-picker-list"
                role="group"
                aria-labelledby={labelId}
                onKeyDown={onKeyDown}
              >
                {available.map((a, i) => {
                  const name = a.title || a.original_filename;
                  return (
                    <button
                      type="button"
                      key={a.id}
                      aria-label={`Choose ${name} ${a.id.slice(0, 8)}`}
                      disabled={disabled}
                      {...itemProps(i, a.id)}
                      onClick={() => {
                        cache.setQueryData(["artifact", a.id], a);
                        onChange(a.id);
                        setLibraryOpen(false);
                      }}
                    >
                      {kind === "image" ? (
                        <img src={`/api/artifacts/${a.id}/thumbnail`} alt="" />
                      ) : kind === "video" ? (
                        <Film size={18} />
                      ) : (
                        <AudioLines size={18} />
                      )}
                      <span>{name}</span>
                    </button>
                  );
                })}
              </div>
            </section>
          )}
        </div>
      )}
      <ErrorNotice error={upload.error ?? source.error ?? library.error} />
    </div>
  );
}
