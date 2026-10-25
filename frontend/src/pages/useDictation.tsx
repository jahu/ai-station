import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Settings2, Square, Upload, X } from "lucide-react";
import { api, type Run } from "../api";
import { randomId } from "../lib/random-id";
import { Button } from "../components/ui/button";
import RecordingButton from "../components/media/RecordingButton";
import { useMediaRun } from "../components/media/media-run";
import { uploadRecordingFiles } from "./recording-upload";

type Snapshot = { text: string; revision: number; start: number; end: number };
type Job = {
  file: File;
  snapshot: Snapshot;
  language: string;
  requestId: string;
  source?: string;
  runId?: string;
  canceled: boolean;
  settled?: boolean;
};
type Transcript = { text: string; artifacts: Record<string, string> };

/** Dictation only prepares a draft; it never invokes a conversation endpoint. */
export function useDictation({
  value,
  onChange,
  textarea,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  textarea: RefObject<HTMLTextAreaElement | null>;
  disabled: boolean;
}) {
  const cache = useQueryClient();
  const ready = useQuery({
    queryKey: ["transcription-capabilities"],
    queryFn: () =>
      api<{ available: boolean; reason?: string }>(
        "/audio/transcription/capabilities",
      ),
    staleTime: 60000,
  });
  const [language, setLanguage] = useState(() => {
    try {
      return localStorage.getItem("ai-station:dictation-language") === "pl"
        ? "pl"
        : "auto";
    } catch {
      return "auto";
    }
  });
  const [options, setOptions] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [phase, setPhase] = useState<
    "idle" | "working" | "stopping" | "failed" | "done" | "conflict"
  >("idle");
  const [error, setError] = useState("");
  const [jobView, setJobView] = useState<Job | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const job = useRef<Job | null>(null);
  const snapshot = useRef<Snapshot | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const draft = useRef({ text: value, revision: 0, onChange });
  useLayoutEffect(() => {
    if (draft.current.text !== value) draft.current.revision++;
    draft.current.text = value;
    draft.current.onChange = onChange;
  }, [value, onChange]);
  const run = useMediaRun(jobView?.runId ?? "");

  function captureSnapshot(): Snapshot {
    return {
      text: draft.current.text,
      revision: draft.current.revision,
      start: textarea.current?.selectionStart ?? draft.current.text.length,
      end: textarea.current?.selectionEnd ?? draft.current.text.length,
    };
  }
  async function cancelRun(id: string) {
    await api(`/runs/${id}/cancel`, { method: "POST" });
    void cache.invalidateQueries({ queryKey: ["run", id] });
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const current = job.current;
      if (!current || current.canceled || current.settled) return;
      current.canceled = true;
      if (current.runId) void cancelRun(current.runId).catch(() => {});
    };
    // The owned job ref survives renders; cleanup also handles late acknowledgements.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function prepare(current: Job) {
    setPhase("working");
    setError("");
    setTranscript(null);
    try {
      if (!current.source) {
        const source = await uploadRecordingFiles(
          [current.file],
          cache,
          () => {},
        );
        current.source = source.id;
      }
      if (!mounted.current) return;
      setJobView({ ...current });
      if (current.canceled) {
        setPhase("failed");
        return;
      }
      const result = await api<Run>("/audio/transcription/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audio_artifact_id: current.source,
          language: current.language,
          client_request_id: current.requestId,
        }),
      });
      current.runId = result.id;
      if (current.canceled || !mounted.current) {
        if (mounted.current) setJobView({ ...current });
        await cancelRun(result.id);
        return;
      }
      cache.setQueryData(["run", result.id], result);
      setJobView({ ...current });
      void cache.invalidateQueries({ queryKey: ["runs"] });
    } catch (cause) {
      if (!mounted.current) return;
      setJobView({ ...current });
      setPhase("failed");
      setError(
        cause instanceof Error ? cause.message : "Could not prepare dictation.",
      );
    }
  }

  async function start(file: File) {
    if (job.current && !job.current.canceled && phase === "working") return;
    const current: Job = {
      file,
      snapshot: snapshot.current ?? captureSnapshot(),
      language,
      requestId: randomId(),
      canceled: false,
    };
    snapshot.current = null;
    job.current = current;
    setJobView({ ...current });
    // Capture finishes immediately; upload/transcription now belong to the job.
    void prepare(current);
  }

  function insert(text: string, mode: "original" | "insert" | "replace") {
    const current = job.current;
    if (!current || current.canceled) return;
    if (
      mode === "original" &&
      current.snapshot.revision !== draft.current.revision
    ) {
      setPhase("conflict");
      return;
    }
    const position = mode === "original" ? current.snapshot : captureSnapshot();
    const prefix =
      mode === "replace" ? "" : draft.current.text.slice(0, position.start);
    const suffix =
      mode === "replace" ? "" : draft.current.text.slice(position.end);
    const addition =
      (prefix && !/\s$/.test(prefix) ? " " : "") +
      text +
      (suffix && !/^\s/.test(suffix) ? " " : "");
    const next = prefix + addition + suffix;
    if (next.length > 32000) {
      setError(
        "The combined draft exceeds 32,000 characters. Shorten it or use the saved transcript.",
      );
      setPhase("conflict");
      return;
    }
    draft.current.onChange(next);
    setPhase("done");
    setError("");
    requestAnimationFrame(() => {
      if (!mounted.current) return;
      textarea.current?.focus();
      textarea.current?.setSelectionRange(
        prefix.length + addition.length,
        prefix.length + addition.length,
      );
    });
  }

  useEffect(() => {
    // Adopt an asynchronously observed result only while this composer still owns it.
    const timer = setTimeout(() => {
      const current = job.current;
      const result = run.data;
      if (
        !mounted.current ||
        !current ||
        !result ||
        result.id !== current.runId
      )
        return;
      if (current.canceled) {
        if (
          ["succeeded", "failed", "canceled", "interrupted"].includes(
            result.status,
          )
        ) {
          current.settled = true;
          if (phase === "stopping") setPhase("failed");
        }
        return;
      }
      if (phase !== "working") return;
      if (result.status === "succeeded") {
        current.settled = true;
        const saved = result.metadata?.transcription as Transcript | undefined;
        if (!saved || typeof saved.text !== "string" || !saved.text.trim()) {
          setError(
            "No speech was detected. Try again or select the spoken language.",
          );
          setPhase("failed");
          return;
        }
        setTranscript(saved);
        insert(saved.text.trim(), "original");
      } else if (
        ["failed", "canceled", "interrupted"].includes(result.status)
      ) {
        current.settled = true;
        setError(
          result.error_message ||
            "Transcription stopped. Your recording is retained; you can retry.",
        );
        setPhase("failed");
      }
    }, 0);
    return () => clearTimeout(timer);
    // Adoption is guarded by job ownership and phase, never by a conversation Send.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.data, phase]);

  async function stop() {
    const current = job.current;
    if (!current) return;
    current.canceled = true;
    setPhase("stopping");
    setJobView({ ...current });
    setError("Stop requested. Your draft is unchanged.");
    try {
      if (current.runId) await cancelRun(current.runId);
    } catch {
      setError(
        "Could not confirm Stop. Inspect the dictation Run before retrying.",
      );
    }
  }

  const busy = capturing || phase === "working" || phase === "stopping";
  const usable = ready.data?.available === true;
  const action = (
    <div className="dictation-actions">
      {phase !== "working" && phase !== "stopping" && (
        <RecordingButton
          mode="dictation"
          disabled={disabled || !usable || phase === "conflict"}
          onBusy={(active) => {
            if (active && !snapshot.current) {
              snapshot.current = captureSnapshot();
              setPhase("idle");
              setError("");
            }
            if (!active) snapshot.current = null;
            setCapturing(active);
          }}
          onRecorded={start}
        />
      )}
      {(phase === "working" || phase === "stopping") && (
        <span className="recording-state" role="status">
          {phase === "stopping" ? "Stopping…" : "Transcribing…"}
        </span>
      )}
      {!capturing && (
        <Button
          type="button"
          variant="ghost"
          aria-label="Dictation options"
          title="Dictation options and audio-file transcription"
          aria-expanded={options}
          onClick={() => setOptions(!options)}
        >
          <Settings2 size={15} />
        </Button>
      )}
    </div>
  );
  const panel = (capturing || options || phase !== "idle") && (
    <section className="dictation-panel" aria-label="Dictation">
      {capturing && (
        <p role="status">
          Stop to transcribe locally. The recording and transcript will be saved
          in Library; nothing is sent automatically.
        </p>
      )}
      {options && (
        <div className="dictation-options">
          <p>
            Dictate an editable draft. Nothing is sent automatically. Recordings
            and transcripts stay in Library.
          </p>
          {window.isSecureContext === false && (
            <p>
              Microphone access requires HTTPS or localhost. On this HTTP
              connection, transcribe an audio file instead.
            </p>
          )}
          {!usable && (
            <p role="status">
              {ready.isPending
                ? "Checking local transcription…"
                : ready.data?.reason ||
                  "Local Whisper is unavailable. Configure offline transcription in Audio."}
            </p>
          )}
          <label>
            Dictation language
            <select
              value={language}
              disabled={busy}
              onChange={(event) => {
                setLanguage(event.target.value);
                try {
                  localStorage.setItem(
                    "ai-station:dictation-language",
                    event.target.value,
                  );
                } catch {
                  /* preference is optional */
                }
              }}
            >
              <option value="auto">Detect automatically</option>
              <option value="pl">Polish</option>
            </select>
          </label>
          <Button
            type="button"
            variant="ghost"
            disabled={disabled || busy || !usable}
            onClick={() => input.current?.click()}
          >
            <Upload size={14} /> Transcribe an audio file
          </Button>
          <input
            ref={input}
            hidden
            type="file"
            aria-label="Dictation audio file"
            accept=".wav,.mp3,.m4a,.ogg,.oga,.webm,.flac"
            disabled={disabled || busy || !usable}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) {
                snapshot.current = captureSnapshot();
                void start(file);
              }
            }}
          />
        </div>
      )}
      {phase === "working" && (
        <div className="row spread">
          <span role="status">
            {jobView?.runId
              ? "Transcribing locally on CPU… Your draft stays editable."
              : "Preparing your recording…"}
          </span>
          <Button type="button" variant="ghost" onClick={() => void stop()}>
            <Square size={14} /> Cancel dictation
          </Button>
        </div>
      )}
      {phase === "stopping" && (
        <div className="row spread">
          <span role="status">
            Waiting for the owned transcription to stop…
          </span>
          <Button type="button" variant="ghost" onClick={() => void stop()}>
            Check Stop again
          </Button>
        </div>
      )}
      {(error || run.error) && (
        <p role="alert">
          {error ||
            "Cannot check transcription progress. The Run may still be active; inspect it or retry the status check."}
        </p>
      )}
      {phase === "working" && run.error && (
        <Button
          type="button"
          variant="ghost"
          onClick={() => void run.refetch()}
        >
          Check transcription again
        </Button>
      )}
      {phase === "failed" && (
        <>
          <p>
            Retry uses this saved recording. An unacknowledged request keeps the
            same identity.
          </p>
          <Button
            type="button"
            variant="secondary"
            disabled={
              disabled ||
              (jobView?.canceled &&
                !!jobView?.runId &&
                !["succeeded", "failed", "canceled", "interrupted"].includes(
                  run.data?.status ?? "",
                ))
            }
            onClick={() => {
              const current = job.current;
              if (!current) return;
              if (current.settled) current.requestId = randomId();
              if (current.settled) current.language = language;
              current.canceled = false;
              current.settled = false;
              current.runId = undefined;
              current.snapshot = captureSnapshot();
              void prepare(current);
            }}
          >
            Retry dictation
          </Button>
        </>
      )}
      {phase === "conflict" && transcript && (
        <div>
          <p>
            Your draft changed while transcribing. Choose how to use the text.
          </p>
          <blockquote>{transcript.text}</blockquote>
          <div className="row">
            <Button
              type="button"
              variant="secondary"
              onClick={() => insert(transcript.text.trim(), "insert")}
            >
              Insert at cursor
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => insert(transcript.text.trim(), "replace")}
            >
              Replace draft
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setPhase("done")}
            >
              Keep my draft
            </Button>
          </div>
        </div>
      )}
      {phase === "done" && (
        <p role="status">
          Dictation ready. Review your draft, then Send when ready.
        </p>
      )}
      {jobView?.source && (
        <details>
          <summary>Saved recording &amp; transcript</summary>
          <audio
            controls
            preload="none"
            aria-label="Dictation recording"
            src={`/api/artifacts/${jobView.source}/file`}
          />
          {jobView.runId && (
            <Link to={`/audio?mode=transcribe&run=${jobView.runId}`}>
              Open transcript
            </Link>
          )}
          <Link to={`/library/${jobView.source}`}>Inspect recording</Link>
        </details>
      )}
      {jobView?.runId && (
        <Link to={`/runs/${jobView.runId}`}>Inspect dictation Run</Link>
      )}
      {!busy && phase !== "conflict" && (
        <Button
          type="button"
          variant="ghost"
          aria-label="Dismiss dictation details"
          onClick={() => {
            setOptions(false);
            setPhase("idle");
            setError("");
          }}
        >
          <X size={14} /> Dismiss
        </Button>
      )}
    </section>
  );
  return { action, panel, busy };
}
