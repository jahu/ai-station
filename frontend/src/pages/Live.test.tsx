import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import Live from "./Live";

const state = vi.hoisted(() => ({
  stop: vi.fn(),
  connect: vi.fn(),
  prepare: vi.fn(),
}));
vi.mock("../api", () => ({ api: vi.fn() }));
vi.mock("../lib/live-capture", () => ({
  LiveCapture: class {
    constructor(
      _input: unknown,
      _output: unknown,
      private changed: (value: unknown) => void,
    ) {}
    prepare = state.prepare;
    connect = state.connect;
    setMonitoring = vi.fn();
    stop() {
      state.stop();
      this.changed({ stopped: true, connected: false });
    }
  },
}));
vi.mock("../components/media/MediaInput", () => ({
  default: (props: {
    label: string;
    value: string;
    disabled: boolean;
    onChange: (value: string) => void;
  }) => (
    <label>
      {props.label}
      <input
        aria-label={props.label}
        value={props.value}
        disabled={props.disabled}
        onChange={(event) => props.onChange(event.target.value)}
      />
    </label>
  ),
}));
vi.mock("./SpeechSetupPanel", () => ({
  EnvironmentSetupPanel: () => <div>Prepare Live runtime</div>,
}));

const queued = {
  run: { id: "run-1", status: "queued", created_at: "2026-11-14T20:00:00Z" },
  ready: false,
};
beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(window, "isSecureContext", {
    value: true,
    configurable: true,
  });
  Object.defineProperty(navigator, "mediaDevices", {
    value: {
      getUserMedia: vi.fn(),
      enumerateDevices: vi.fn().mockResolvedValue([]),
    },
    configurable: true,
  });
  state.prepare.mockResolvedValue(undefined);
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/live/capabilities")
      return { available: true, eligible_gpu_indices: [3, 7] } as never;
    if (path === "/live/sessions") return [] as never;
    if (path === "/live/sessions/run-1") return queued as never;
    return {} as never;
  });
});
afterEach(cleanup);
function open() {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={cache}>
      <MemoryRouter>
        <Live />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...view, cache };
}

it("explains private HTTPS instead of starting inaccessible LAN capture", async () => {
  Object.defineProperty(window, "isSecureContext", {
    value: false,
    configurable: true,
  });
  vi.mocked(api).mockImplementation(async (path) =>
    path === "/live/capabilities"
      ? ({ available: true, secure_origin: "https://station.example" } as never)
      : ([] as never),
  );
  open();
  expect(
    await screen.findByRole("link", {
      name: "Open AI Station over private HTTPS",
    }),
  ).toHaveProperty("href", "https://station.example/#/live");
  fireEvent.change(screen.getByLabelText("Reference portrait"), {
    target: { value: "face-1" },
  });
  expect(
    screen.getByRole("button", { name: "Start live session" }),
  ).toHaveProperty("disabled", true);
  expect(state.prepare).not.toHaveBeenCalled();
});

it("queues a session only after device permission and stops capture plus its Run", async () => {
  const base = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, options) =>
    path === "/live/sessions" && options?.method === "POST"
      ? (queued as never)
      : base(path, options),
  );
  const view = open();
  await screen.findByText("Ready when you are");
  fireEvent.change(screen.getByLabelText("Reference portrait"), {
    target: { value: "face-1" },
  });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Start live session" }),
    ).toHaveProperty("disabled", false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Start live session" }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/live/sessions",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(state.prepare).toHaveBeenCalledWith(
    expect.objectContaining({ face: true, voice: false }),
  );
  expect(state.connect).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Stop session" }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/runs/run-1/cancel",
      expect.objectContaining({ method: "POST", keepalive: true }),
    ),
  );
  expect(state.stop).toHaveBeenCalled();
  view.unmount();
});

it("cancels a delayed enqueue acknowledgement after the user has already stopped", async () => {
  let resolve!: (value: never) => void;
  const base = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, options) =>
    path === "/live/sessions" && options?.method === "POST"
      ? new Promise((done) => {
          resolve = done;
        })
      : base(path, options),
  );
  open();
  fireEvent.change(screen.getByLabelText("Reference portrait"), {
    target: { value: "face-1" },
  });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Start live session" }),
    ).toHaveProperty("disabled", false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Start live session" }));
  await waitFor(() => expect(resolve).toBeTypeOf("function"));
  fireEvent.click(screen.getByRole("button", { name: "Stop session" }));
  resolve(queued as never);
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/runs/run-1/cancel", { method: "POST" }),
  );
  expect(state.connect).not.toHaveBeenCalled();
});

it("checks portrait readiness independently and preserves the working face-swap choice", async () => {
  const base = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, options) =>
    path === "/live/capabilities?mode=portrait"
      ? ({
          available: false,
          reason: "Prepare the portrait extension",
          eligible_gpu_indices: [3, 7],
        } as never)
      : base(path, options),
  );
  open();
  fireEvent.change(screen.getByLabelText("Reference portrait"), {
    target: { value: "face-1" },
  });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Start live session" }),
    ).toHaveProperty("disabled", false),
  );
  fireEvent.click(screen.getByRole("button", { name: /^Animated portrait/ }));
  await screen.findByText("Prepare the portrait extension");
  expect(
    screen.getByRole("button", { name: "Start live session" }),
  ).toHaveProperty("disabled", true);
  expect(state.prepare).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /^Face swap/ }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Start live session" }),
    ).toHaveProperty("disabled", false),
  );
});

it("requires a portrait image and freezes the mode once capture starts", async () => {
  const base = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, options) =>
    path === "/live/capabilities?mode=portrait"
      ? ({ available: true, eligible_gpu_indices: [3, 7] } as never)
      : path === "/live/sessions" && options?.method === "POST"
        ? (queued as never)
        : base(path, options),
  );
  open();
  fireEvent.click(screen.getByRole("button", { name: /^Animated portrait/ }));
  fireEvent.change(screen.getByLabelText("Reference voice"), {
    target: { value: "voice-1" },
  });
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/live/capabilities?mode=portrait"),
  );
  expect(
    screen.getByRole("button", { name: "Start live session" }),
  ).toHaveProperty("disabled", true);
  fireEvent.change(screen.getByLabelText("Reference portrait"), {
    target: { value: "face-1" },
  });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Start live session" }),
    ).toHaveProperty("disabled", false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Start live session" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /^Face swap/ })).toHaveProperty(
      "disabled",
      true,
    ),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/live/sessions",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"mode":"portrait"'),
      }),
    ),
  );
  expect(state.prepare).toHaveBeenCalledWith(
    expect.objectContaining({ face: true, voice: true }),
  );
});
