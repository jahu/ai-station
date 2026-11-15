import {
  decodeLivePacket,
  encodeLivePacket,
  type LivePacket,
} from "./live-protocol";

export type LiveCaptureState = {
  connected?: boolean;
  stopped?: boolean;
  microphone?: number;
  voice?: number;
  fps?: number;
  voiceMs?: number;
  faceMs?: number;
  delayMs?: number;
  tracking?: boolean;
  buffering?: boolean;
};

/** Browser-owned capture. Only converted output reaches the canvas/speakers. */
export class LiveCapture {
  private media?: MediaStream;
  private context?: AudioContext;
  private capture?: AudioWorkletNode;
  private playback?: AudioWorkletNode;
  private monitor?: GainNode;
  private socket?: WebSocket;
  private stopped = false;
  private timer?: ReturnType<typeof setTimeout>;
  private animation?: number;
  private anchor?: number;
  private startAt = 0;
  private frameSequence = 0;
  private facePending = false;
  private lastCameraAt = 0;
  private lastTrackingPause = -1;
  private pictures: (LivePacket & { bitmap: ImageBitmap })[] = [];
  private playbackUs = -1;
  private tracking = false;
  private receivedFrames = 0;
  private frameWindow = performance.now();
  private canvas = document.createElement("canvas");

  constructor(
    private input: HTMLVideoElement,
    private output: HTMLCanvasElement,
    private changed: (state: LiveCaptureState) => void,
    private failed: (message: string) => void,
  ) {}

  async prepare({
    face,
    voice,
    camera,
    microphone,
  }: {
    face: boolean;
    voice: boolean;
    camera?: string;
    microphone?: string;
  }) {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)
      throw new Error(
        "Open AI Station over HTTPS or localhost to use camera and microphone.",
      );
    // Create/resume synchronously in the Start gesture, before waiting on a Run.
    if (voice) {
      this.context = new AudioContext({ latencyHint: "interactive" });
      await this.context.resume();
      await this.context.audioWorklet.addModule(
        new URL("./live-audio-worklet.js", import.meta.url),
      );
    }
    const media = await navigator.mediaDevices.getUserMedia({
      video: face
        ? {
            width: { ideal: 640, max: 640 },
            height: { ideal: 480, max: 480 },
            frameRate: { ideal: 15, max: 20 },
            ...(camera ? { deviceId: { exact: camera } } : {}),
          }
        : false,
      audio: voice
        ? {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: false,
            ...(microphone ? { deviceId: { exact: microphone } } : {}),
          }
        : false,
    });
    if (this.stopped) {
      media.getTracks().forEach((track) => track.stop());
      return;
    }
    this.media = media;
    for (const track of media.getTracks())
      track.onended = () =>
        this.fail("Camera or microphone disconnected. Start a new session.");
    if (face) {
      this.input.muted = true;
      this.input.playsInline = true;
      this.input.srcObject = media;
      await this.input.play();
      this.output.width = this.canvas.width = this.input.videoWidth;
      this.output.height = this.canvas.height = this.input.videoHeight;
    }
  }

  connect(runId: string) {
    if (this.stopped || !this.media || this.socket) return;
    const socket = new WebSocket(
      `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/live/sessions/${runId}/stream`,
    );
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    socket.onopen = () => {
      if (this.stopped) return;
      this.changed({ connected: true });
      this.startAt = performance.now();
      if (this.context && this.media?.getAudioTracks().length) {
        const context = this.context;
        this.capture = new AudioWorkletNode(context, "station-live-audio", {
          processorOptions: { mode: "capture" },
        });
        this.playback = new AudioWorkletNode(context, "station-live-audio", {
          processorOptions: { mode: "playback" },
        });
        this.monitor = context.createGain();
        this.monitor.gain.value = 0;
        context.createMediaStreamSource(this.media).connect(this.capture);
        this.capture.connect(context.destination); // Worklet output is always zero.
        this.playback.connect(this.monitor).connect(context.destination);
        this.capture.port.onmessage = ({ data }) => {
          if (data.type === "captured") {
            this.anchor = data.startFrame / context.sampleRate;
            this.send(
              encodeLivePacket({
                kind: 2,
                sequence: data.sequence,
                timestampUs: data.timestampUs,
                body: data.samples,
              }),
            );
          } else if (data.type === "level")
            this.changed({ microphone: data.rms });
          else if (data.type === "error") this.fail(data.message);
        };
        this.playback.port.onmessage = ({ data }) => {
          if (data.type === "clock") {
            this.playbackUs = data.sourceUs;
            this.changed({
              buffering: false,
              delayMs: Math.max(0, (this.sourceUs() - data.sourceUs) / 1000),
            });
          } else if (data.type === "buffering")
            this.changed({ buffering: true });
          else if (data.type === "error") this.fail(data.message);
        };
      }
      if (this.media?.getVideoTracks().length) {
        void this.cameraFrame();
        this.paint();
      }
    };
    socket.onmessage = ({ data }) => {
      if (this.stopped) return;
      if (typeof data === "string") {
        try {
          const value = JSON.parse(data);
          if (typeof value.error === "string") {
            const reasons: Record<string, string> = {
              input_overload:
                "Live input is arriving faster than the engine can process. The session stopped to avoid accumulating delay.",
              processing_timeout:
                "The live engine or connection stopped responding. Start a new session.",
              engine_connection_ended:
                "A live inference engine stopped. Open the session details to inspect its error.",
              invalid_media_packet:
                "The live media clock or packet was invalid. Start a fresh session.",
            };
            this.fail(
              reasons[value.error] ??
                "Live processing failed. Open the session details to inspect the error.",
            );
            return;
          }
          if (value.face) {
            this.facePending = false;
            this.tracking = value.face.tracking === true;
            this.changed({
              tracking: this.tracking,
              faceMs: value.face.inference_ms,
            });
            if (!this.tracking) {
              this.lastTrackingPause = Math.max(
                this.lastTrackingPause,
                value.face.sequence ?? -1,
              );
              this.clearPictures();
              this.output
                .getContext("2d")
                ?.clearRect(0, 0, this.output.width, this.output.height);
            }
            if (!this.stopped) {
              if (this.timer) clearTimeout(this.timer);
              // Acknowledge-driven pacing avoids skipping an entire 65-ms
              // tick when inference takes slightly longer than one frame.
              this.timer = setTimeout(
                () => void this.cameraFrame(),
                Math.max(0, 65 - (performance.now() - this.lastCameraAt)),
              );
            }
          }
          if (value.voice) this.changed({ voiceMs: value.voice.inference_ms });
        } catch {
          this.fail("Invalid live engine observation.");
        }
        return;
      }
      try {
        const packet = decodeLivePacket(data);
        if (packet.kind === 18) {
          const samples = new Float32Array(packet.body);
          this.changed({
            voice: Math.sqrt(
              samples.reduce((sum, value) => sum + value * value, 0) /
                samples.length,
            ),
          });
          this.playback?.port.postMessage(
            {
              type: "block",
              timestampUs: packet.timestampUs,
              samples: packet.body,
            },
            [packet.body],
          );
        } else {
          void this.picture(packet).catch(() =>
            this.fail("The converted video could not be decoded."),
          );
        }
      } catch {
        this.fail("The live engine returned an invalid media packet.");
      }
    };
    socket.onerror = () =>
      this.fail("Could not connect to the live engine. Start a new session.");
    socket.onclose = () => {
      if (!this.stopped)
        this.fail("Live connection ended. Camera and microphone have stopped.");
    };
  }

  setMonitoring(enabled: boolean) {
    if (this.monitor && this.context)
      this.monitor.gain.setTargetAtTime(
        enabled ? 1 : 0,
        this.context.currentTime,
        0.02,
      );
  }

  private sourceUs() {
    return Math.max(
      0,
      Math.round(
        (this.context && this.anchor !== undefined
          ? this.context.currentTime - this.anchor
          : (performance.now() - this.startAt) / 1000) * 1e6,
      ),
    );
  }

  private send(raw: ArrayBuffer) {
    if (this.stopped || this.socket?.readyState !== WebSocket.OPEN) return;
    if (this.socket.bufferedAmount > 1024 * 1024) {
      this.fail(
        "The connection cannot keep up. Live stopped instead of accumulating delay.",
      );
      return;
    }
    this.socket.send(raw);
  }

  private async cameraFrame() {
    if (this.stopped || this.facePending) return;
    try {
      if (
        !this.facePending &&
        this.socket?.readyState === WebSocket.OPEN &&
        (!this.context || this.anchor !== undefined)
      ) {
        this.lastCameraAt = performance.now();
        this.canvas
          .getContext("2d")!
          .drawImage(this.input, 0, 0, this.canvas.width, this.canvas.height);
        const timestampUs = this.sourceUs();
        const blob = await new Promise<Blob | null>((resolve) =>
          this.canvas.toBlob(resolve, "image/jpeg", 0.85),
        );
        if (blob && !this.stopped) {
          this.facePending = true;
          this.send(
            encodeLivePacket({
              kind: 1,
              sequence: this.frameSequence++,
              timestampUs,
              body: await blob.arrayBuffer(),
            }),
          );
        }
      }
    } catch {
      this.fail("Camera capture failed. Start a new session.");
    }
    if (!this.stopped && !this.facePending)
      this.timer = setTimeout(() => void this.cameraFrame(), 25);
  }

  private async picture(packet: LivePacket) {
    const bitmap = await createImageBitmap(
      new Blob([packet.body], { type: "image/jpeg" }),
    );
    if (this.stopped || packet.sequence <= this.lastTrackingPause) {
      bitmap.close();
      return;
    }
    if (this.pictures.length >= 20) {
      bitmap.close();
      this.fail("Video preview cannot keep up. Start a new session.");
      return;
    }
    this.pictures.push({ ...packet, bitmap });
    this.pictures.sort((a, b) => a.timestampUs - b.timestampUs);
    this.receivedFrames++;
    const elapsed = performance.now() - this.frameWindow;
    if (elapsed >= 1000) {
      this.changed({ fps: (this.receivedFrames * 1000) / elapsed });
      this.receivedFrames = 0;
      this.frameWindow = performance.now();
    }
  }

  private paint = () => {
    if (this.stopped) return;
    const clock = this.context ? this.playbackUs : Infinity;
    let latest: (LivePacket & { bitmap: ImageBitmap }) | undefined;
    while (this.pictures.length && this.pictures[0].timestampUs <= clock) {
      latest?.bitmap.close();
      latest = this.pictures.shift();
    }
    if (latest) {
      if (this.tracking) {
        // Render the engine's geometry, which may differ from the webcam input.
        if (this.output.width !== latest.bitmap.width)
          this.output.width = latest.bitmap.width;
        if (this.output.height !== latest.bitmap.height)
          this.output.height = latest.bitmap.height;
        this.output
          .getContext("2d")
          ?.drawImage(
            latest.bitmap,
            0,
            0,
            this.output.width,
            this.output.height,
          );
      }
      latest.bitmap.close();
    }
    this.animation = requestAnimationFrame(this.paint);
  };

  private clearPictures() {
    for (const picture of this.pictures) picture.bitmap.close();
    this.pictures = [];
  }
  private fail(message: string) {
    if (this.stopped) return;
    this.stop();
    this.failed(message);
  }
  stop() {
    if (this.stopped) return;
    this.stopped = true;
    this.changed({ connected: false, stopped: true });
    if (this.timer) clearTimeout(this.timer);
    if (this.animation) cancelAnimationFrame(this.animation);
    this.media?.getTracks().forEach((track) => track.stop());
    this.input.srcObject = null;
    this.capture?.port.postMessage({ type: "stop" });
    this.playback?.port.postMessage({ type: "stop" });
    this.capture?.disconnect();
    this.playback?.disconnect();
    this.monitor?.disconnect();
    this.socket?.close();
    void this.context?.close().catch(() => undefined);
    this.clearPictures();
    this.output
      .getContext("2d")
      ?.clearRect(0, 0, this.output.width, this.output.height);
  }
}
