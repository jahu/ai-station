import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { AudioLines, Copy, Download, FileText, Square } from "lucide-react";
import { api, type Run } from "../api";
import { Badge, ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import MediaInput from "../components/media/MediaInput";
import { mediaBusy, useMediaRun } from "../components/media/media-run";

type Transcript = {
  model?: string;
  text: string;
  language: string;
  duration_seconds: number;
  segments: { start: number; end: number; text: string }[];
  artifacts: Record<string, string>;
};
const time = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`;

export function TranscriptResult({ run }: { run: Run }) {
  const transcript = run.metadata?.transcription as Transcript | undefined;
  const [copied, setCopied] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const sourceId = (
    run.parameters?.parent_artifact_ids as string[] | undefined
  )?.[0];
  const [copyError, setCopyError] = useState<Error | null>(null);
  if (run.status !== "succeeded" || !transcript) return null;
  return (
    <section aria-label="Transcript" className="transcript-result">
      <div className="transcript-heading">
        <h2>Your recording, in words</h2>
        <span className="chip">
          {transcript.language.toUpperCase()} ·{" "}
          {time(transcript.duration_seconds)}
        </span>
      </div>
      {sourceId && (
        <audio
          ref={audioRef}
          controls
          preload="metadata"
          src={`/api/artifacts/${sourceId}/file`}
          aria-label="Original recording"
        />
      )}
      <div className="transcript-actions">
        <Button
          type="button"
          variant="secondary"
          disabled={!transcript.text}
          onClick={() => {
            void navigator.clipboard.writeText(transcript.text).then(
              () => {
                setCopied(true);
                setCopyError(null);
              },
              () =>
                setCopyError(
                  new Error("Copy failed. Download the text instead."),
                ),
            );
          }}
        >
          <Copy size={15} />
          {copied ? "Copied" : "Copy text"}
        </Button>
        {[
          ["txt", "Text"],
          ["srt", "Subtitles"],
          ["json", "JSON"],
        ].map(([kind, label]) => (
          <a
            className="button secondary"
            key={kind}
            href={`/api/artifacts/${transcript.artifacts[kind]}/file`}
            download={`transcript.${kind}`}
          >
            <Download size={14} />
            {label}
          </a>
        ))}
      </div>
      <ErrorNotice error={copyError} />
      {!transcript.text ? (
        <p className="muted">
          No speech was detected. Try a clearer recording or choose its language
          explicitly.
        </p>
      ) : (
        <ol className="transcript-segments">
          {transcript.segments.map((segment, i) => (
            <li key={i}>
              {sourceId ? (
                <button
                  type="button"
                  className="transcript-time"
                  aria-label={`Play recording from ${time(segment.start)}`}
                  onClick={() => {
                    if (audioRef.current) {
                      audioRef.current.currentTime = segment.start;
                      void audioRef.current
                        .play()
                        .catch(() =>
                          setCopyError(
                            new Error(
                              "Start playback using the audio controls.",
                            ),
                          ),
                        );
                    }
                  }}
                >
                  {time(segment.start)}–{time(segment.end)}
                </button>
              ) : (
                <span>
                  {time(segment.start)}–{time(segment.end)}
                </span>
              )}
              <p>{segment.text}</p>
            </li>
          ))}
        </ol>
      )}
      {transcript.model && (
        <p className="transcript-model">{transcript.model} · CPU</p>
      )}
      <p className="media-privacy">
        Machine transcription can contain mistakes. Check names and important
        details against the recording.
      </p>
    </section>
  );
}

export default function Transcription() {
  const [search, setSearch] = useSearchParams();
  const [source, setSource] = useState<string | null>(search.get("input"));
  const [language, setLanguage] = useState("auto");
  const [uploading, setUploading] = useState(false);
  const cache = useQueryClient();
  const capabilities = useQuery({
    queryKey: ["transcription-capabilities"],
    queryFn: () =>
      api<{ available: boolean; reason?: string }>(
        "/audio/transcription/capabilities",
      ),
  });
  const runId = search.get("run") ?? "";
  const run = useMediaRun(runId);
  const selectedSource =
    source ??
    (run.data?.parameters?.parent_artifact_ids as string[] | undefined)?.[0] ??
    "";
  const submit = useMutation({
    mutationFn: () =>
      api<Run>("/audio/transcription/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audio_artifact_id: selectedSource, language }),
      }),
    onSuccess: (result) => {
      cache.setQueryData(["run", result.id], result);
      setSearch((current) => {
        const next = new URLSearchParams(current);
        next.set("run", result.id);
        return next;
      });
    },
  });
  const stop = useMutation({
    mutationFn: () => api(`/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["run", runId] }),
  });
  const busy = submit.isPending || mediaBusy(run.data);
  return (
    <>
      <PageTitle
        eyebrow="CREATE / AUDIO"
        title="Turn recordings into words."
        action={
          <span className="media-runtime">
            {capabilities.data?.available && <i />}
            {capabilities.isPending
              ? "Checking Whisper…"
              : capabilities.data?.available
                ? "Whisper · Local CPU"
                : "Whisper · Setup required"}
          </span>
        }
      >
        Transcribe a recording privately. Keep the original, read timestamped
        speech and download text or subtitles.
      </PageTitle>
      <div className="media-workspace">
        <form
          className="panel media-composer"
          onSubmit={(event) => {
            event.preventDefault();
            if (
              selectedSource &&
              !busy &&
              !uploading &&
              capabilities.data?.available
            )
              submit.mutate();
          }}
        >
          <div className="media-composer-heading">
            <AudioLines size={20} />
            <h2>Transcribe recording</h2>
          </div>
          <fieldset disabled={busy || uploading}>
            <MediaInput
              kind="audio"
              label="Recording"
              hint="WAV, MP3, M4A, Ogg, WebM or FLAC · 5 min · 20 MB"
              value={selectedSource}
              onChange={setSource}
              disabled={busy || uploading}
              onBusy={setUploading}
              uploadEndpoint="/audio/transcription/uploads"
              maxAudioSeconds={300}
              audioMode="transcription"
            />
            <label>
              Spoken language
              <select
                aria-label="Spoken language"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
              >
                {[
                  ["auto", "Detect automatically"],
                  ["pl", "Polish"],
                  ["en", "English"],
                  ["de", "German"],
                  ["fr", "French"],
                  ["es", "Spanish"],
                  ["it", "Italian"],
                  ["pt", "Portuguese"],
                  ["uk", "Ukrainian"],
                  ["ru", "Russian"],
                ].map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <ErrorNotice error={capabilities.error || submit.error} />
            {capabilities.data && !capabilities.data.available && (
              <p role="status" className="muted">
                {capabilities.data.reason}
              </p>
            )}
            <Button
              type="submit"
              className="media-generate"
              disabled={
                !selectedSource ||
                busy ||
                uploading ||
                !capabilities.data?.available
              }
            >
              <FileText size={17} />
              {busy ? "Transcribing…" : "Transcribe recording"}
            </Button>
            <p className="media-privacy">
              Audio stays on this workstation. Runs on CPU; your GPUs remain
              available.
            </p>
          </fieldset>
        </form>
        <div
          className="panel media-result transcription-output"
          aria-live="polite"
        >
          {run.data ? (
            <>
              <div className="media-result-heading">
                <Badge status={run.data.status} />
                <Link to={`/runs/${runId}`}>Inspect run</Link>
              </div>
              {busy && (
                <>
                  <p>Processing your recording locally…</p>
                  <Button
                    variant="secondary"
                    disabled={
                      stop.isPending || run.data.status === "cancel_requested"
                    }
                    onClick={() => stop.mutate()}
                  >
                    <Square size={14} />
                    Stop transcription
                  </Button>
                </>
              )}
              <TranscriptResult key={run.data.id} run={run.data} />
              {run.data.status === "failed" && (
                <p role="alert">
                  {run.data.error_message ||
                    "Transcription failed. Inspect the run for details."}
                </p>
              )}
              {["canceled", "interrupted"].includes(run.data.status) && (
                <p>
                  Transcription stopped. Your recording is preserved; you can
                  start a new run.
                </p>
              )}
            </>
          ) : (
            <div className="media-empty">
              <FileText size={40} />
              <h2>A clear transcript, right here.</h2>
              <p>Choose a recording to get timestamped text and subtitles.</p>
            </div>
          )}
          <ErrorNotice error={run.error || stop.error} />
        </div>
      </div>
    </>
  );
}
