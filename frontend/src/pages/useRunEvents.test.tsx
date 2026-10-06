import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { RunEvent } from "../api";
import { useRunEvents } from "./useRunEvents";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("resumes after initial history and merges streamed events without refetching history per token", async () => {
  const event = (sequence: number): RunEvent => ({
    id: String(sequence),
    sequence,
    event_type: "agent.delta",
    payload: { text: "token" },
    created_at: "2026-10-06T10:00:00Z",
  });
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => [event(1)] });
  vi.stubGlobal("fetch", fetch);
  const streams: FakeSource[] = [];
  class FakeSource {
    onmessage: ((event: { data: string }) => void) | null = null;
    close = vi.fn();
    end: (() => void) | null = null;
    constructor(public url: string) {
      streams.push(this);
    }
    addEventListener(_name: string, handler: () => void) {
      this.end = handler;
    }
  }
  vi.stubGlobal("EventSource", FakeSource);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const { result, unmount } = renderHook(() => useRunEvents("run"), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
  await waitFor(() =>
    expect(streams[0].url).toBe("/api/runs/run/stream?after=1"),
  );
  act(() => {
    for (let i = 2; i <= 101; i++)
      streams[0].onmessage?.({ data: JSON.stringify(event(i)) });
    streams[0].onmessage?.({ data: JSON.stringify(event(2)) });
  });
  await waitFor(() => expect(result.current.data).toHaveLength(101));
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(result.current.data?.at(-1)?.sequence).toBe(101);
  act(() => {
    streams[0].onmessage?.({ data: JSON.stringify(event(102)) });
    streams[0].end?.();
  });
  expect(client.getQueryData<RunEvent[]>(["events", "run"])).toHaveLength(102);
  expect(streams[0].close).toHaveBeenCalled();
  unmount();
});
