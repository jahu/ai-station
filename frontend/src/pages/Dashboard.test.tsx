import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Dashboard from "./Dashboard";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function gpu(index: number, uuid: string) {
  return {
    index,
    uuid,
    name: `NVIDIA GPU ${index}`,
    utilization: 10 + index,
    memory_used_mib: 1000,
    memory_total_mib: 12288,
    temperature_c: 40,
    fan_percent: 30,
    power_watts: 80,
  };
}

function mount() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("moves through Home GPU cards with arrow keys without inventing a Run", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () => {
      if (url.includes("/system/hardware")) {
        return {
          gpus: [gpu(0, "gpu-zero-aaaa"), gpu(1, "gpu-one-bbbbbb")],
          cpu: { utilization: 8, temperature_c: 35 },
          memory: {
            total_mib: 64000,
            used_mib: 16000,
            available_mib: 48000,
            swap_used_mib: 0,
            swap_total_mib: 0,
          },
          disk: { total_bytes: 1e12, used_bytes: 2e11, free_bytes: 8e11 },
          load: {},
        };
      }
      if (url.includes("/system/status")) return { counts: {} };
      if (url.includes("/system/history")) return [];
      return {
        active_run_count: 0,
        enabled_agent_count: 0,
        active_runs: [],
        upcoming: [],
        agents: [],
        conversations: [],
        artifacts: [],
        runtimes: [],
      };
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  const first = await screen.findByLabelText("GPU 0 gpu-zero");
  const second = screen.getByLabelText("GPU 1 gpu-one-");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Compute" })).toBeTruthy();
  expect(
    screen.getByText(/Use arrow keys to move between detected GPUs/),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".gpu-grid") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".gpu-grid") as HTMLElement, {
    key: "Enter",
  });
  expect(fetch.mock.calls.every((call) => call.length === 1 || !call[1])).toBe(
    true,
  );
  fireEvent.keyDown(second.closest(".gpu-grid") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});

it("moves through Home CPU and memory cards without inventing a Run", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () => {
      if (url.includes("/system/hardware")) {
        return {
          gpus: [gpu(0, "gpu-zero-aaaa")],
          cpu: { utilization: 8, temperature_c: 35 },
          memory: {
            total_mib: 64000,
            used_mib: 16000,
            available_mib: 48000,
            swap_used_mib: 0,
            swap_total_mib: 0,
          },
          disk: { total_bytes: 1e12, used_bytes: 2e11, free_bytes: 8e11 },
          load: {},
        };
      }
      if (url.includes("/system/status")) return { counts: {} };
      if (url.includes("/system/history")) return [];
      return {
        active_run_count: 0,
        enabled_agent_count: 0,
        active_runs: [],
        upcoming: [],
        agents: [],
        conversations: [],
        artifacts: [],
        runtimes: [],
      };
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  const cpu = await screen.findByLabelText("Metric CPU");
  const memory = screen.getByLabelText("Metric memory");
  const storage = screen.getByLabelText("Metric storage");
  const runs = screen.getByLabelText("Metric runs");
  expect(cpu.tabIndex).toBe(0);
  expect(memory.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable telemetry Run/),
  ).toBeTruthy();
  fireEvent.keyDown(cpu.closest(".metrics-grid") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(memory.tabIndex).toBe(0);
  expect(document.activeElement).toBe(memory);
  fireEvent.keyDown(memory.closest(".metrics-grid") as HTMLElement, {
    key: "Enter",
  });
  expect(fetch.mock.calls.every((call) => call.length === 1 || !call[1])).toBe(
    true,
  );
  fireEvent.keyDown(memory.closest(".metrics-grid") as HTMLElement, {
    key: "End",
  });
  expect(runs.tabIndex).toBe(0);
  expect(storage.tabIndex).toBe(-1);
  fireEvent.keyDown(runs.closest(".metrics-grid") as HTMLElement, {
    key: "Home",
  });
  expect(cpu.tabIndex).toBe(0);
});
