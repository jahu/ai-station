import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import RecordingButton from "./RecordingButton";

const stopTrack = vi.fn();
const stream = { getTracks: () => [{ stop: stopTrack }] };
let instances: FakeRecorder[];
class FakeRecorder {
  static isTypeSupported = () => true;
  state = "inactive";
  mimeType = "audio/webm;codecs=opus";
  ondataavailable?: (event: { data: Blob }) => void;
  onstop?: () => void;
  onerror?: () => void;
  constructor() {
    instances.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({
      data: new Blob(["recorded-audio"], { type: this.mimeType }),
    });
    this.onstop?.();
  }
}
beforeEach(() => {
  instances = [];
  stopTrack.mockClear();
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  vi.stubGlobal("navigator", {
    mediaDevices: { getUserMedia: vi.fn(async () => stream) },
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
function mount() {
  const onRecorded = vi.fn<(_file: File) => Promise<void>>(async () => {});
  const onBusy = vi.fn();
  const view = render(
    <RecordingButton
      disabled={false}
      onBusy={onBusy}
      onRecorded={onRecorded}
    />,
  );
  return { ...view, onRecorded, onBusy };
}
it("releases microphone and stages one recording only after Finish", async () => {
  const { onRecorded, onBusy } = mount();
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Record audio" }));
  await screen.findByRole("button", { name: "Finish recording" });
  expect(onRecorded).not.toHaveBeenCalled();
  expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({
    audio: true,
  });
  fireEvent.click(screen.getByRole("button", { name: "Finish recording" }));
  await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1));
  expect(onRecorded.mock.calls[0][0]).toMatchObject({
    name: "recording.webm",
    type: "audio/webm;codecs=opus",
  });
  expect(stopTrack).toHaveBeenCalled();
  await waitFor(() => expect(onBusy).toHaveBeenLastCalledWith(false));
});
it("cancels without uploading, including late microphone permission", async () => {
  let allow!: (value: unknown) => void;
  vi.mocked(navigator.mediaDevices.getUserMedia).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        allow = resolve as (value: unknown) => void;
      }),
  );
  const { onRecorded, onBusy } = mount();
  fireEvent.click(screen.getByRole("button", { name: "Record audio" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel recording" }));
  await act(async () => allow(stream));
  expect(stopTrack).toHaveBeenCalled();
  expect(instances).toHaveLength(0);
  expect(onRecorded).not.toHaveBeenCalled();
  expect(onBusy).toHaveBeenLastCalledWith(false);
});
it("releases an active microphone when leaving the composer without uploading", async () => {
  const { unmount, onRecorded } = mount();
  fireEvent.click(screen.getByRole("button", { name: "Record audio" }));
  await screen.findByRole("button", { name: "Finish recording" });
  unmount();
  expect(stopTrack).toHaveBeenCalled();
  expect(onRecorded).not.toHaveBeenCalled();
});
it("shows actionable denied-permission feedback", async () => {
  vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(
    new DOMException("Denied", "NotAllowedError"),
  );
  const { onRecorded, onBusy } = mount();
  fireEvent.click(screen.getByRole("button", { name: "Record audio" }));
  expect((await screen.findByRole("alert")).textContent).toContain(
    "permission was denied",
  );
  expect(onRecorded).not.toHaveBeenCalled();
  expect(onBusy).toHaveBeenLastCalledWith(false);
});
it("rejects an oversized capture without uploading", async () => {
  const { onRecorded } = mount();
  fireEvent.click(screen.getByRole("button", { name: "Record audio" }));
  await screen.findByRole("button", { name: "Finish recording" });
  act(() =>
    instances[0].ondataavailable?.({
      data: new Blob([new Uint8Array(21 * 1024 * 1024)]),
    }),
  );
  expect(screen.getByRole("alert").textContent).toContain("20 MiB");
  expect(stopTrack).toHaveBeenCalled();
  expect(onRecorded).not.toHaveBeenCalled();
});
it("finishes automatically before the five-minute decoder bound", async () => {
  vi.useFakeTimers();
  const { onRecorded } = mount();
  await act(async () =>
    fireEvent.click(screen.getByRole("button", { name: "Record audio" })),
  );
  await act(async () => vi.advanceTimersByTime(295000));
  expect(onRecorded).toHaveBeenCalledTimes(1);
  expect(stopTrack).toHaveBeenCalled();
});

it("retains the captured file for retry after an upload failure", async () => {
  const { onRecorded } = mount();
  onRecorded.mockRejectedValueOnce(new Error("Offline"));
  fireEvent.click(screen.getByRole("button", { name: "Record audio" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Finish recording" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Retry attachment" }),
  );
  await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(2));
  expect(onRecorded.mock.calls[0][0]).toBe(onRecorded.mock.calls[1][0]);
  await screen.findByRole("button", { name: "Record audio" });
  expect(instances).toHaveLength(1);
});
