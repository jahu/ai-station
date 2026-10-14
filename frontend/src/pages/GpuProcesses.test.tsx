import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import GpuProcesses, { type GpuProcessObservation } from "./GpuProcesses";
import type { GPU } from "../api";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(data: GpuProcessObservation) {
  const fetch = vi.fn(async () => ({ ok: true, json: async () => data }));
  vi.stubGlobal("fetch", fetch);
  const gpu = {
    index: 7,
    uuid: "GPU-test",
    name: "Test GPU",
    utilization: null,
    memory_used_mib: null,
    memory_total_mib: null,
    temperature_c: null,
    fan_percent: null,
    power_watts: null,
  } satisfies GPU;
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <GpuProcesses gpus={[gpu]} />
    </QueryClientProvider>,
  );
  return fetch;
}
it("maps UUID to discovered GPU and shows read-only process memory", async () => {
  const fetch = mount({
    status: "available",
    sampled_at: "2026-10-14T08:00:00Z",
    truncated: false,
    processes: [
      { gpu_uuid: "GPU-test", pid: 1234, name: "python", memory_used_mib: 512 },
    ],
  });
  await screen.findByText("python");
  expect(screen.getByText("GPU 7")).toBeTruthy();
  expect(screen.getByText("1234")).toBeTruthy();
  expect(screen.getByText("512 MiB")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
  expect(fetch).toHaveBeenCalledWith("/api/system/gpu-processes", undefined);
});
it.each(["unavailable", "partial"] as const)(
  "does not call %s results an empty healthy GPU",
  async (status) => {
    mount({ status, sampled_at: null, truncated: false, processes: [] });
    await screen.findByText(
      status === "unavailable"
        ? "Compute-process reporting is unavailable on this host."
        : "No valid process records were returned.",
    );
    expect(
      screen.queryByText("No compute processes were reported."),
    ).toBeNull();
  },
);
it("makes truncated observations explicit", async () => {
  mount({
    status: "available",
    sampled_at: null,
    truncated: true,
    processes: [],
  });
  await screen.findByText(/This observation is incomplete/);
});
