import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ModelSetup from "./ModelSetup";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const entry = {
  id: "small",
  name: "Local starter",
  quantization: "Q4_K_M",
  file: { size_bytes: 2497281312, sha256: "a".repeat(64) },
  license: "Apache-2.0",
  license_url: "https://models.example.com/license",
  source_url: "https://models.example.com/model",
  revision: "pinned",
  manifest_sha256: "b".repeat(64),
  model_file_id: null,
  recommendation: {
    fits: true,
    reason: "Estimated fit",
    gpus: [7],
    context_size: 32768,
  },
};
function mount(
  canPrepare = true,
  initial: unknown[] = [],
  freeBytes = 20 * 1024 ** 3,
  selectedEntry?: Record<string, unknown>,
) {
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  let rows = initial;
  let verified = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        writes.push({ url, body });
        if (url.endsWith("/install"))
          return {
            ok: true,
            json: async () => ({ id: "readiness-run", status: "queued" }),
          };
        if (url.endsWith("/chat/conversations"))
          return { ok: true, json: async () => ({ id: "new-chat" }) };
        if (url.endsWith("/cancel"))
          rows = [{ ...preparation("canceled"), resume_allowed: true }];
        else if (url.endsWith("/resume"))
          rows = [
            {
              ...preparation("queued"),
              attempt: 2,
              run: { id: "new-run", status: "queued", error_message: "" },
            },
          ];
        else rows = [preparation("queued")];
        return { ok: true, json: async () => rows[0] };
      }
      if (url.endsWith("/runs/readiness-run")) {
        verified = true;
        return {
          ok: true,
          json: async () => ({ id: "readiness-run", status: "succeeded" }),
        };
      }
      if (url.endsWith("/setup/runtimes"))
        return {
          ok: true,
          json: async () => ({
            usable_image: true,
            installation_available: false,
          }),
        };
      if (url.includes("/setup/runtimes/preparations"))
        return { ok: true, json: async () => [] };
      return {
        ok: true,
        json: async () =>
          url.endsWith("/setup/catalog")
            ? {
                can_prepare: canPrepare,
                entries: [
                  {
                    ...(selectedEntry ?? entry),
                    ...(verified ? { ready_to_try: true } : {}),
                  },
                ],
                hardware: {
                  memory: { total_mib: 32768 },
                  gpus: [
                    { index: 7, name: "Detected GPU", memory_total_mib: 12288 },
                  ],
                },
                storage: {
                  free_bytes: freeBytes,
                  total_bytes: 100 * 1024 ** 3,
                  headroom_bytes: 256 * 1024 ** 2,
                },
              }
            : rows,
      };
    }),
  );
  const view = render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<ModelSetup />} />
          <Route path="/chat/:id" element={<p>Conversation opened</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { writes, ...view };
}
function preparation(status: string) {
  return {
    id: "preparation",
    entry,
    attempt: 1,
    run: { id: "original-run", status, error_message: "" },
    model_key: null,
    resume_allowed: false,
    progress: {
      phase: "downloading",
      received_bytes: 1024 ** 3,
      expected_bytes: entry.file.size_bytes,
    },
  };
}

it("queues only a reviewed pinned model after explicit license acceptance, retaining resumable history", async () => {
  const { writes } = mount();
  const button = await screen.findByRole("button", {
    name: "Download 2.33 GiB",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: /I have reviewed/ }));
  fireEvent.click(button);
  await screen.findByLabelText("Download progress preparat");
  expect(writes).toHaveLength(1);
  expect(writes[0].body).toMatchObject({
    catalog_id: "small",
    manifest_sha256: "b".repeat(64),
    license_accepted: true,
  });
  expect(writes[0].body.client_request_id).toBeTruthy();
  expect(writes[0].body.url).toBeUndefined();
  expect(screen.getByText(/1.00 GiB of 2.33 GiB/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Resume preparation" }),
  );
  await waitFor(() => expect(writes).toHaveLength(3));
  expect(writes[2].body.expected_run_id).toBe("original-run");
});

it("restores a completed preparation and opens an empty local conversation only on explicit request", async () => {
  const finished = {
    ...preparation("succeeded"),
    model_key: "llamacpp:shared-model",
    progress: { phase: "files_verified", ready_to_try: true },
  };
  const { writes } = mount(true, [finished]);
  fireEvent.click(
    await screen.findByRole("button", { name: "Open Chat with this model" }),
  );
  expect(await screen.findByText("Conversation opened")).toBeTruthy();
  expect(writes).toHaveLength(1);
  expect(writes[0].url).toBe("/api/chat/conversations");
  expect(writes[0].body).toEqual({
    model: "llamacpp:shared-model",
    execution_mode: "assistant",
  });
});

it("shows shared choices while leaving installation to the administrator", async () => {
  const { writes } = mount(false);
  expect(await screen.findByText(/Your administrator manages/)).toBeTruthy();
  expect(
    (
      screen.getByRole("checkbox", {
        name: /I have reviewed/,
      }) as HTMLInputElement
    ).disabled,
  ).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "Download 2.33 GiB",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(writes).toEqual([]);
});

it("does not present downloaded weights as an available runtime", async () => {
  mount(true, [
    {
      ...preparation("succeeded"),
      progress: { phase: "files_verified", ready_to_try: false },
    },
  ]);
  expect(
    await screen.findByText(
      /Compatible runtime or hardware setup is still needed/,
    ),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Open Chat with this model" }),
  ).toBeNull();
});

it("restores the active preparation instead of submitting a duplicate download", async () => {
  const { writes } = mount(true, [preparation("running")]);
  fireEvent.click(
    await screen.findByRole("button", { name: "View existing preparation" }),
  );
  expect(document.activeElement).toBe(
    screen.getByRole("article", { name: "Model preparation preparat" }),
  );
  expect(
    screen.queryByRole("button", { name: "Download 2.33 GiB" }),
  ).toBeNull();
  expect(writes).toEqual([]);
});

it("shows free application storage and prevents a download that cannot fit", async () => {
  const { writes } = mount(true, [], 1024 ** 3);
  expect(
    await screen.findByText(/1.00 GiB free in AI Station storage/),
  ).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain(
    "More free AI Station storage is needed",
  );
  fireEvent.click(screen.getByRole("checkbox", { name: /I have reviewed/ }));
  expect(
    (
      screen.getByRole("button", {
        name: "Download 2.33 GiB",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(writes).toEqual([]);
});

it("verifies previously downloaded model files without another download or automatic inference", async () => {
  const { writes } = mount(true, [], 20 * 1024 ** 3, {
    ...entry,
    model_file_id: "shared-file",
    definition_id: "shared-definition",
    ready_to_try: false,
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Verify model readiness" }),
  );
  await screen.findByRole("button", { name: "Open Chat with this model" });
  expect(writes).toHaveLength(1);
  expect(writes[0].url).toBe(
    "/api/models/definitions/shared-definition/install",
  );
  expect(writes[0].body).toEqual({});
});
