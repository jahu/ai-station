import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { LiveCapture } from "./live-capture";
import { encodeLivePacket } from "./live-protocol";

class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 1;
  bufferedAmount = 0;
  binaryType = "";
  onopen?: () => void;
  onclose?: () => void;
  onerror?: () => void;
  onmessage?: (event: { data: string | ArrayBuffer }) => void;
  send = vi.fn();
  close = vi.fn();
  constructor() {
    Socket.instances.push(this);
  }
}
beforeEach(() => {
  Socket.instances = [];
  vi.stubGlobal("WebSocket", Socket);
  Object.defineProperty(window, "isSecureContext", {
    value: true,
    configurable: true,
  });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    clearRect: vi.fn(),
    drawImage: vi.fn(),
  } as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(
    () => undefined,
  );
  vi.stubGlobal("requestAnimationFrame", vi.fn().mockReturnValue(1));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("captures the next frame on acknowledgement without skipping a whole timer tick", async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
  vi.mocked(HTMLCanvasElement.prototype.toBlob).mockImplementation((done) =>
    done({
      arrayBuffer: async () => new Uint8Array([255, 216, 255, 217]).buffer,
    } as Blob),
  );
  const { video } = devices();
  const capture = new LiveCapture(
    video,
    document.createElement("canvas"),
    vi.fn(),
    vi.fn(),
  );
  await capture.prepare({ face: true, voice: false });
  capture.connect("run-1");
  const socket = Socket.instances[0];
  socket.onopen?.();
  await vi.advanceTimersByTimeAsync(0);
  expect(socket.send).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(75);
  expect(socket.send).toHaveBeenCalledTimes(1);
  socket.onmessage?.({
    data: JSON.stringify({
      face: { sequence: 0, tracking: true, inference_ms: 75 },
    }),
  });
  await vi.advanceTimersByTimeAsync(0);
  expect(socket.send).toHaveBeenCalledTimes(2);
  capture.stop();
});
function devices(getUserMedia?: () => Promise<unknown>) {
  const track = { stop: vi.fn(), onended: null };
  const media = {
    getTracks: () => [track],
    getVideoTracks: () => [track],
    getAudioTracks: () => [],
  };
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia: getUserMedia ?? vi.fn().mockResolvedValue(media) },
    configurable: true,
  });
  const video = document.createElement("video");
  video.play = vi.fn().mockResolvedValue(undefined);
  Object.defineProperties(video, {
    videoWidth: { value: 640 },
    videoHeight: { value: 480 },
  });
  return { track, media, video };
}

it("never reconnects capture implicitly and closes every owned track on transport failure", async () => {
  const { track, video } = devices();
  const failed = vi.fn();
  const capture = new LiveCapture(
    video,
    document.createElement("canvas"),
    vi.fn(),
    failed,
  );
  await capture.prepare({ face: true, voice: false });
  capture.connect("run-1");
  capture.connect("run-1");
  expect(Socket.instances).toHaveLength(1);
  Socket.instances[0].onopen?.();
  Socket.instances[0].onerror?.();
  expect(track.stop).toHaveBeenCalledOnce();
  expect(Socket.instances[0].close).toHaveBeenCalledOnce();
  expect(video.srcObject).toBeNull();
  expect(failed).toHaveBeenCalledWith(
    expect.stringContaining("Could not connect"),
  );
  capture.connect("run-1");
  expect(Socket.instances).toHaveLength(1);
});

it("stops late permission results instead of leaving a camera active after Stop", async () => {
  let resolve!: (value: unknown) => void;
  const { track, media, video } = devices(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const capture = new LiveCapture(
    video,
    document.createElement("canvas"),
    vi.fn(),
    vi.fn(),
  );
  const opening = capture.prepare({ face: true, voice: false });
  capture.stop();
  resolve(media);
  await opening;
  expect(track.stop).toHaveBeenCalledOnce();
  expect(video.play).not.toHaveBeenCalled();
  expect(Socket.instances).toHaveLength(0);
});

it.each([
  [512, 512],
  [640, 480],
])(
  "preserves converted picture geometry %sx%s independently of the webcam",
  async (width, height) => {
    const { video } = devices();
    const output = document.createElement("canvas");
    const bitmap = { width, height, close: vi.fn() };
    vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue(bitmap));
    const capture = new LiveCapture(video, output, vi.fn(), vi.fn());
    await capture.prepare({ face: true, voice: false });
    expect([output.width, output.height]).toEqual([640, 480]);
    capture.connect("run-1");
    const socket = Socket.instances[0];
    socket.onopen?.();
    socket.onmessage?.({
      data: JSON.stringify({ face: { sequence: 0, tracking: true } }),
    });
    socket.onmessage?.({
      data: encodeLivePacket({
        kind: 17,
        sequence: 0,
        timestampUs: 0,
        body: new Uint8Array([255, 216, 255, 217]).buffer,
      }),
    });
    await vi.waitFor(() => expect(createImageBitmap).toHaveBeenCalledOnce());
    const paint = vi.mocked(requestAnimationFrame).mock.calls.at(-1)![0];
    paint(performance.now());
    expect([output.width, output.height]).toEqual([width, height]);
    expect(bitmap.close).toHaveBeenCalledOnce();
    expect(video.videoWidth).toBe(640);
    expect(video.videoHeight).toBe(480);
    capture.stop();
  },
);
