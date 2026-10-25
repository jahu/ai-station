import { useEffect, useRef, useState } from "react";
import { Mic, Square, X } from "lucide-react";
import { Button } from "../ui/button";

const MAX_BYTES = 20 * 1024 * 1024;
const MAX_SECONDS = 295;
const FORMATS = [
  ["audio/webm;codecs=opus", "webm"],
  ["audio/ogg;codecs=opus", "ogg"],
  ["audio/mp4", "m4a"],
];

type Capture = {
  active: boolean;
  recorder?: MediaRecorder;
  stream?: MediaStream;
  timer?: ReturnType<typeof setInterval>;
  file?: File;
};

export default function RecordingButton({
  disabled,
  onBusy,
  onRecorded,
  mode = "attachment",
}: {
  disabled: boolean;
  onBusy: (busy: boolean) => void;
  onRecorded: (file: File) => Promise<void>;
  mode?: "attachment" | "dictation";
}) {
  const [phase, setPhase] = useState("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  const current = useRef<Capture | null>(null);
  const callbacks = useRef({ onBusy, onRecorded });
  useEffect(() => {
    callbacks.current = { onBusy, onRecorded };
  }, [onBusy, onRecorded]);
  function release(capture: Capture) {
    clearInterval(capture.timer);
    capture.stream?.getTracks().forEach((track) => track.stop());
  }
  function cancel() {
    const capture = current.current;
    if (!capture) return;
    capture.active = false;
    if (capture.recorder?.state === "recording") capture.recorder.stop();
    release(capture);
    current.current = null;
    setPhase("idle");
    callbacks.current.onBusy(false);
  }
  useEffect(
    () => () => {
      const capture = current.current;
      if (!capture) return;
      capture.active = false;
      if (capture.recorder?.state === "recording") capture.recorder.stop();
      release(capture);
      callbacks.current.onBusy(false);
    },
    [],
  );

  async function attach(capture: Capture) {
    if (!capture.active || !capture.file) return;
    setPhase("uploading");
    setError("");
    callbacks.current.onBusy(true);
    try {
      await callbacks.current.onRecorded(capture.file);
      if (capture.active) {
        capture.active = false;
        current.current = null;
        setPhase("idle");
      }
    } catch {
      if (capture.active) {
        setPhase("retry");
        setError(
          mode === "dictation"
            ? "Could not prepare dictation. Retry without recording again, or cancel."
            : "Could not attach the recording. Retry without recording again, or cancel.",
        );
      }
    } finally {
      if (current.current === capture || !current.current)
        callbacks.current.onBusy(false);
    }
  }

  async function start() {
    if (current.current || disabled) return;
    setError("");
    if (window.isSecureContext === false) {
      setError(
        "Microphone access requires HTTPS or localhost. Transcribe an audio file instead.",
      );
      return;
    }
    if (
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      setError(
        "Recording is unavailable in this browser. Attach an audio file instead.",
      );
      return;
    }
    const format = FORMATS.find(([mime]) =>
      MediaRecorder.isTypeSupported(mime),
    );
    if (!format) {
      setError("No supported recording format. Attach an audio file instead.");
      return;
    }
    const capture: Capture = { active: true };
    current.current = capture;
    setPhase("requesting");
    callbacks.current.onBusy(true);
    try {
      capture.stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      if (!capture.active) {
        release(capture);
        return;
      }
      const recorder = new MediaRecorder(capture.stream, {
        mimeType: format[0],
        audioBitsPerSecond: 64000,
      });
      capture.recorder = recorder;
      const chunks: Blob[] = [];
      let size = 0;
      recorder.ondataavailable = (event) => {
        if (!capture.active || !event.data.size) return;
        size += event.data.size;
        if (size > MAX_BYTES) {
          setError("Recording exceeds 20 MiB. Record a shorter clip.");
          cancel();
          return;
        }
        chunks.push(event.data);
      };
      recorder.onerror = () => {
        if (!capture.active) return;
        setError("Microphone recording failed. Try again or attach a file.");
        cancel();
      };
      recorder.onstop = async () => {
        release(capture);
        if (!capture.active) return;
        if (!size) {
          setError("The recording is empty. Try again.");
          cancel();
          return;
        }
        capture.file = new File(chunks, `recording.${format[1]}`, {
          type: recorder.mimeType || format[0],
        });
        await attach(capture);
      };
      recorder.start(1000);
      setPhase("recording");
      setSeconds(0);
      const started = performance.now();
      capture.timer = setInterval(() => {
        const elapsed = Math.floor((performance.now() - started) / 1000);
        setSeconds(elapsed);
        if (elapsed >= MAX_SECONDS && recorder.state === "recording")
          recorder.stop();
      }, 250);
    } catch (cause) {
      release(capture);
      if (!capture.active) return;
      setError(
        cause instanceof DOMException && cause.name === "NotAllowedError"
          ? "Microphone permission was denied. Allow access in your browser or attach a file."
          : "Microphone is unavailable. Check that it is connected or attach a file.",
      );
      cancel();
    }
  }
  return (
    <div className="recording-control">
      {phase === "idle" ? (
        <Button
          type="button"
          variant="ghost"
          aria-label={mode === "dictation" ? "Dictate" : "Record audio"}
          title={
            mode === "dictation"
              ? "Dictate a draft using local transcription"
              : "Attach a recording for analysis"
          }
          disabled={disabled}
          onClick={start}
        >
          <Mic size={15} /> {mode === "dictation" ? "Dictate" : "Record audio"}
        </Button>
      ) : (
        <>
          <span className="recording-state" role="status">
            {phase === "recording"
              ? `Recording · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`
              : phase === "requesting"
                ? "Waiting for microphone…"
                : phase === "retry"
                  ? "Recording ready"
                  : mode === "dictation"
                    ? "Preparing dictation…"
                    : "Attaching recording…"}
          </span>
          {phase === "recording" && (
            <Button
              type="button"
              onClick={() => {
                setPhase("uploading");
                current.current?.recorder?.stop();
              }}
            >
              <Square size={14} />{" "}
              {mode === "dictation" ? "Stop recording" : "Finish recording"}
            </Button>
          )}
          {phase === "retry" && (
            <Button
              type="button"
              disabled={disabled}
              onClick={() => {
                if (current.current) void attach(current.current);
              }}
            >
              Retry attachment
            </Button>
          )}
          {phase !== "uploading" && (
            <Button type="button" variant="ghost" onClick={cancel}>
              <X size={15} /> Cancel recording
            </Button>
          )}
        </>
      )}
      {error && (
        <span className="recording-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
