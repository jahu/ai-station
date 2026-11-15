import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Camera,
  Headphones,
  Mic,
  Play,
  ShieldCheck,
  Square,
} from "lucide-react";
import { api, type Run } from "../api";
import { Badge, ErrorNotice, PageTitle } from "../components/common";
import MediaInput from "../components/media/MediaInput";
import { Button } from "../components/ui/button";
import { LiveCapture, type LiveCaptureState } from "../lib/live-capture";
import { randomId } from "../lib/random-id";
import { EnvironmentSetupPanel } from "./SpeechSetupPanel";
import "./live.css";

type Session = { run: Run; ready: boolean };
type Capabilities = {
  available: boolean;
  reason?: string;
  eligible_gpu_indices?: number[];
  secure_origin?: string;
  can_prepare?: boolean;
};
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);

export default function Live() {
  const cache = useQueryClient();
  const [mode, setMode] = useState<"face_swap" | "portrait">("face_swap");
  const [image, setImage] = useState("");
  const [voice, setVoice] = useState("");
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [runId, setRunId] = useState("");
  const [status, setStatus] = useState<LiveCaptureState>({});
  const [monitoring, setMonitoring] = useState(false);
  const [localPreview, setLocalPreview] = useState(false);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [camera, setCamera] = useState("");
  const [microphone, setMicrophone] = useState("");
  const input = useRef<HTMLVideoElement>(null);
  const output = useRef<HTMLCanvasElement>(null);
  const capture = useRef<LiveCapture | null>(null);
  const active = useRef("");
  const cancelled = useRef(false);
  const live = status.connected === true;
  const busy = !status.stopped && (starting || !!runId);
  const secure =
    window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;
  const capabilities = useQuery({
    queryKey: ["live-capabilities", mode],
    queryFn: () =>
      api<Capabilities>(
        "/live/capabilities" + (mode === "portrait" ? "?mode=portrait" : ""),
      ),
    refetchInterval: busy ? false : 10000,
  });
  const history = useQuery({
    queryKey: ["live-history"],
    queryFn: () => api<Session[]>("/live/sessions"),
    refetchInterval: 3000,
  });
  const session = useQuery({
    queryKey: ["live-session", runId],
    queryFn: () => api<Session>(`/live/sessions/${runId}`),
    enabled: !!runId,
    refetchInterval: (query) =>
      query.state.data && terminal.has(query.state.data.run.status)
        ? false
        : 700,
  });

  function stopCapture() {
    cancelled.current = true;
    capture.current?.stop();
    capture.current = null;
  }
  async function stop() {
    stopCapture();
    setStarting(false);
    setMonitoring(false);
    const identity = active.current;
    active.current = "";
    if (identity) {
      try {
        await api(`/runs/${identity}/cancel`, {
          method: "POST",
          keepalive: true,
        });
      } catch (cause) {
        setError(cause as Error);
      }
    }
    void cache.invalidateQueries({ queryKey: ["live-history"] });
  }

  useEffect(() => {
    const close = () => {
      cancelled.current = true;
      capture.current?.stop();
      capture.current = null;
      const identity = active.current;
      active.current = "";
      if (identity)
        void api(`/runs/${identity}/cancel`, {
          method: "POST",
          keepalive: true,
        }).catch(() => undefined);
    };
    window.addEventListener("pagehide", close);
    window.addEventListener("ai-station:session-expired", close);
    return () => {
      window.removeEventListener("pagehide", close);
      window.removeEventListener("ai-station:session-expired", close);
      close();
    };
  }, []);

  useEffect(() => {
    if (!session.data || !capture.current || cancelled.current) return;
    if (terminal.has(session.data.run.status)) {
      capture.current.stop();
      capture.current = null;
      active.current = "";
    } else if (session.data.ready && !live) {
      capture.current.connect(session.data.run.id);
      capture.current.setMonitoring(monitoring);
    }
  }, [session.data, live, monitoring]);

  async function start() {
    if (!input.current || !output.current || busy) return;
    setError(null);
    setRunId("");
    setStatus({});
    setStarting(true);
    setMonitoring(false);
    cancelled.current = false;
    const controller = new LiveCapture(
      input.current,
      output.current,
      (value) => setStatus((previous) => ({ ...previous, ...value })),
      (message) => {
        setError(new Error(message));
        void stop();
      },
    );
    capture.current = controller;
    try {
      await controller.prepare({
        face: !!image,
        voice: !!voice,
        camera,
        microphone,
      });
      if (cancelled.current || capture.current !== controller) return;
      setDevices(await navigator.mediaDevices.enumerateDevices());
      const result = await api<Session>("/live/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_request_id: randomId(),
          mode,
          image_artifact_id: image || null,
          voice_artifact_id: voice || null,
          maximum_seconds: 1800,
        }),
      });
      if (cancelled.current || capture.current !== controller) {
        await api(`/runs/${result.run.id}/cancel`, { method: "POST" });
        return;
      }
      active.current = result.run.id;
      setRunId(result.run.id);
      cache.setQueryData(["live-session", result.run.id], result);
      setStarting(false);
      void cache.invalidateQueries({ queryKey: ["live-history"] });
    } catch (cause) {
      if (capture.current !== controller || cancelled.current) return;
      controller.stop();
      capture.current = null;
      setError(cause as Error);
      setStarting(false);
    }
  }

  const pending = busy && !live;
  const gpuCount = capabilities.data?.eligible_gpu_indices?.length ?? 0;
  const insufficient = !!image && !!voice && gpuCount < 2;
  const state = live
    ? "Live"
    : pending
      ? session.data?.run.status === "queued"
        ? "Waiting for resources"
        : "Loading local engines"
      : "Ready when you are";
  const endedUnexpectedly =
    session.data && ["failed", "interrupted"].includes(session.data.run.status);
  const sessionError = endedUnexpectedly
    ? new Error(
        "The live engine stopped. Start a new session or open its details to inspect the cause.",
      )
    : null;

  return (
    <div className="live-workspace">
      <PageTitle
        eyebrow="EXPERIMENTAL · LOCAL"
        title="Live"
        action={
          busy ? (
            <Button variant="secondary" onClick={() => void stop()}>
              <Square size={16} />
              Stop session
            </Button>
          ) : undefined
        }
      >
        A different face. A different voice. Still you, in real time.
      </PageTitle>
      <ErrorNotice
        error={
          error ??
          capabilities.error ??
          history.error ??
          session.error ??
          sessionError
        }
      />
      {endedUnexpectedly && (
        <Link className="text-link" to={`/runs/${runId}`}>
          Inspect this session
        </Link>
      )}
      {!secure && (
        <div className="notice">
          <ShieldCheck size={20} />
          <div>
            Camera and microphone need a secure connection.{" "}
            {capabilities.data?.secure_origin ? (
              <a href={`${capabilities.data.secure_origin}/#/live`}>
                Open AI Station over private HTTPS
              </a>
            ) : (
              "Open this station over HTTPS, or use localhost on the station itself."
            )}
          </div>
        </div>
      )}
      <div
        className="live-mode-selector"
        role="group"
        aria-label="Live visual mode"
      >
        {(
          [
            [
              "face_swap",
              "Face swap",
              "Replace your face and keep your camera scene.",
            ],
            [
              "portrait",
              "Animated portrait",
              "Bring the reference portrait to life with your expressions.",
            ],
          ] as const
        ).map(([value, title, description]) => (
          <button
            key={value}
            type="button"
            aria-pressed={mode === value}
            disabled={busy}
            onClick={() => {
              setMode(value);
              setError(null);
              setRunId("");
              setStatus({});
            }}
          >
            <strong>{title}</strong>
            <span>{description}</span>
          </button>
        ))}
      </div>
      {mode === "portrait" && (
        <p className="muted live-mode-hint">
          The portrait supplies the whole rendered head, including hair and
          skin. Start facing the camera with a relaxed expression to calibrate
          motion. Keep your head visible; large turns may pause tracking.
        </p>
      )}
      <div className="live-layout">
        <section
          className="panel live-stage"
          aria-label="Transformed live preview"
        >
          <div className="live-stage-bar">
            <span className={live ? "live-status is-live" : "live-status"}>
              <span />
              {state}
            </span>
            <span className="muted">Nothing recorded</span>
          </div>
          <div className="live-preview">
            <canvas
              ref={output}
              aria-label="Converted camera output"
              className={
                !live || !image || status.tracking === false
                  ? "live-canvas-hidden"
                  : ""
              }
            />
            {(!live || !image || status.tracking === false) && (
              <div className="live-preview-empty">
                {voice && !image ? <Mic size={42} /> : <Camera size={42} />}
                <h2>
                  {pending
                    ? "Preparing your session"
                    : live && status.tracking === false
                      ? "Face tracking paused"
                      : live && !image
                        ? "Your converted voice is live"
                        : mode === "portrait"
                          ? "Your animated portrait"
                          : "Your transformed preview"}
                </h2>
                <p>
                  {pending
                    ? "Your devices are open locally. Streaming begins when the reserved engines are ready."
                    : live && status.tracking === false
                      ? "Keep one face clearly visible. The original camera image is never used as a fallback."
                      : "Choose a portrait or voice, then start. Your original microphone is never played through."}
                </p>
              </div>
            )}
            <video
              ref={input}
              muted
              playsInline
              className={
                localPreview && busy && image
                  ? "live-local-preview"
                  : "live-device-hidden"
              }
              aria-label="Local unconverted camera preview"
            />
          </div>
          <div className="live-meter-grid">
            <label>
              <span>Microphone</span>
              <meter
                min="0"
                max="0.3"
                value={busy ? (status.microphone ?? 0) : 0}
                aria-label="Microphone level"
              />
            </label>
            <label>
              <span>Converted voice</span>
              <meter
                min="0"
                max="0.3"
                value={live ? (status.voice ?? 0) : 0}
                aria-label="Converted voice level"
              />
            </label>
          </div>
          <div className="live-stage-options">
            <label>
              <input
                type="checkbox"
                checked={monitoring && live}
                disabled={!live || !voice}
                onChange={(event) => {
                  setMonitoring(event.target.checked);
                  capture.current?.setMonitoring(event.target.checked);
                }}
              />
              <Headphones size={16} />
              Hear converted voice
            </label>
            <label>
              <input
                type="checkbox"
                checked={localPreview}
                disabled={!image}
                onChange={(event) => setLocalPreview(event.target.checked)}
              />
              Show local input
            </label>
          </div>
          <p className="muted setup-small">
            Use headphones to prevent feedback. Preview monitoring starts muted.
            This session ends after 30 minutes; leaving the page stops capture.
          </p>
          {live && (
            <div className="live-metrics" aria-live="off">
              <span>{status.fps?.toFixed(1) ?? "—"} fps</span>
              <span>
                {mode === "portrait" ? "Portrait" : "Face"}{" "}
                {status.faceMs?.toFixed(0) ?? "—"} ms
              </span>
              <span>Voice {status.voiceMs?.toFixed(0) ?? "—"} ms / 200 ms</span>
              <span>
                {status.buffering
                  ? "Buffering audio"
                  : `Preview delay ${status.delayMs?.toFixed(0) ?? "—"} ms`}
              </span>
            </div>
          )}
        </section>
        <aside
          className="panel live-controls"
          aria-label="Live references and devices"
        >
          <div>
            <h2>Your references</h2>
            <p className="muted">
              {mode === "portrait"
                ? "Choose a portrait. Add a voice reference if you also want to transform your microphone."
                : "Use either medium, or both. Each keeps the same reference for the whole session."}
            </p>
          </div>
          <MediaInput
            kind="image"
            label="Reference portrait"
            hint={
              mode === "portrait"
                ? "Frontal head-and-shoulders portrait · PNG or JPEG"
                : "One clear face · PNG or JPEG"
            }
            value={image}
            onChange={setImage}
            disabled={busy}
            onBusy={setUploading}
          />
          <MediaInput
            kind="audio"
            label="Reference voice"
            hint="Clear speech · WAV recording · at least one second"
            value={voice}
            onChange={setVoice}
            disabled={busy}
            onBusy={setUploading}
            maxAudioSeconds={30}
          />
          <details>
            <summary>Camera & microphone</summary>
            <p className="muted setup-small">
              Device names appear after you grant browser permission.
            </p>
            <label>
              Camera
              <select
                disabled={busy}
                value={camera}
                onChange={(event) => setCamera(event.target.value)}
              >
                <option value="">Browser default</option>
                {devices
                  .filter((device) => device.kind === "videoinput")
                  .map((device, index) => (
                    <option key={device.deviceId} value={device.deviceId}>
                      {device.label || `Camera ${index + 1}`}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Microphone
              <select
                disabled={busy}
                value={microphone}
                onChange={(event) => setMicrophone(event.target.value)}
              >
                <option value="">Browser default</option>
                {devices
                  .filter((device) => device.kind === "audioinput")
                  .map((device, index) => (
                    <option key={device.deviceId} value={device.deviceId}>
                      {device.label || `Microphone ${index + 1}`}
                    </option>
                  ))}
              </select>
            </label>
          </details>
          {insufficient && (
            <p className="notice">
              {mode === "portrait"
                ? "Portrait and voice together need two compatible GPUs. Remove the voice reference to animate the portrait on one GPU."
                : "Both media need two compatible GPUs. Choose just a portrait or voice to use one GPU."}
            </p>
          )}
          {!capabilities.data?.available && (
            <p className="muted">
              {capabilities.data?.reason || "Checking local Live readiness…"}
            </p>
          )}
          <Button
            className="live-start"
            disabled={
              !busy &&
              (uploading ||
                (!image && !voice) ||
                (mode === "portrait" && !image) ||
                !secure ||
                !capabilities.data?.available ||
                insufficient)
            }
            onClick={() => (busy ? void stop() : void start())}
          >
            {busy ? <Square size={16} /> : <Play size={16} />}
            {busy ? "Stop live session" : "Start live session"}
          </Button>
          <p className="muted setup-small">
            <ShieldCheck size={14} />
            Processed locally. Camera and microphone samples stay out of Library
            and logs.
          </p>
        </aside>
      </div>
      {!capabilities.data?.available && (
        <EnvironmentSetupPanel
          key={mode}
          family={mode === "portrait" ? "portrait" : "live"}
        />
      )}
      {!!history.data?.length && (
        <details className="panel live-history">
          <summary>
            Recent sessions{" "}
            <span className="muted">({history.data.length})</span>
          </summary>
          {history.data.map(({ run }) => (
            <div className="row spread" key={run.id}>
              <Link to={`/runs/${run.id}`}>
                {run.parameters?.mode === "portrait"
                  ? "Animated portrait"
                  : "Face / voice"}{" "}
                · {new Date(run.created_at).toLocaleString()}
              </Link>
              <Badge status={run.status} />
              {!terminal.has(run.status) && (
                <Button
                  variant="secondary"
                  onClick={() =>
                    void api(`/runs/${run.id}/cancel`, { method: "POST" })
                      .then(() =>
                        cache.invalidateQueries({ queryKey: ["live-history"] }),
                      )
                      .catch((cause) => setError(cause as Error))
                  }
                >
                  <Square size={14} />
                  Stop
                </Button>
              )}
            </div>
          ))}
        </details>
      )}
    </div>
  );
}
