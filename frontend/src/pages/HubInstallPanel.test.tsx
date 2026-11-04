import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import HubInstallPanel, { type InstallPlan } from "./HubInstallPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const plan: InstallPlan = {
  manifest_sha256: "a".repeat(64),
  license: "apache-2.0",
  license_url: "https://huggingface.co/publisher/new-model",
  files: [
    {
      assessment: {
        hardware_status: "estimated_fit",
        disk: { status: "file_fits" },
      },
    },
  ],
};
function mount(currentPlan = plan, downloadId = "", onDownload = vi.fn()) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <HubInstallPanel
          plan={currentPlan}
          runId="reviewed-plan"
          canManage={true}
          downloadId={downloadId}
          onDownload={onDownload}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onDownload;
}
it("requires explicit license acceptance and sends only the saved plan identity", async () => {
  const fetch = vi.fn(async (_path: string, _options?: RequestInit) => ({
    ok: _path === "/api/model-hub/downloads" && _options?.method === "POST",
    json: async () => ({ id: "preparation" }),
  }));
  vi.stubGlobal("fetch", fetch);
  const accepted = mount();
  const button = screen.getByRole("button", {
    name: "Install model",
  }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() => expect(accepted).toHaveBeenCalledWith("preparation"));
  const [path, options] = fetch.mock.calls[0];
  expect(path).toBe("/api/model-hub/downloads");
  expect(JSON.parse(String(options?.body))).toEqual({
    client_request_id: expect.any(String),
    plan_run_id: "reviewed-plan",
    manifest_sha256: plan.manifest_sha256,
    license_accepted: true,
  });
});
it("keeps installation disabled when no workload fits", () => {
  mount({
    ...plan,
    files: [
      {
        assessment: {
          hardware_status: "unknown",
          disk: { status: "file_fits" },
        },
      },
    ],
  });
  fireEvent.click(screen.getByRole("checkbox"));
  expect(
    (screen.getByRole("button", { name: "Install model" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});
it("restores owned download progress and reuses existing Stop action without another install", async () => {
  const fetch = vi.fn(async (_path: string, _options?: RequestInit) => ({
    ok:
      _path.startsWith("/api/setup/downloads/") &&
      ["GET", "POST"].includes(_options?.method ?? "GET"),
    json: async () => ({
      id: "preparation",
      manifest_sha256: plan.manifest_sha256,
      entry: {
        name: "New model",
        file: { size_bytes: 4096, sha256: "b".repeat(64) },
        quantization: "Q4_K_M",
      },
      attempt: 1,
      run: { id: "download-run", status: "running", error_message: "" },
      model_key: null,
      resume_allowed: false,
      progress: {
        phase: "downloading",
        received_bytes: 1024,
        expected_bytes: 4096,
      },
    }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount(plan, "preparation");
  await screen.findByRole("progressbar");
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([p, o]) =>
          p === "/api/setup/downloads/preparation/cancel" &&
          o?.method === "POST",
      ),
    ).toBe(true),
  );
  expect(fetch.mock.calls.some(([p]) => p === "/api/model-hub/downloads")).toBe(
    false,
  );
});
