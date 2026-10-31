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
import RuntimeSetupPanel from "./RuntimeSetupPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const recipe = {
  profile: "llamacpp-cuda-linux-amd64-v1",
  name: "llama.cpp",
  download_bytes: 2589389163,
  license: "Runtime licenses",
  license_url: "https://example.com/license",
  cuda_license_url: "https://example.com/cuda",
  image_reference: "ghcr.io/ggml-org/llama.cpp@sha256:" + "a".repeat(64),
};
function preparation(status: string) {
  return {
    id: "runtime-prep",
    recipe,
    attempt: 1,
    run: { id: "runtime-run", status, created_at: "2026-10-31T00:00:00Z" },
    resume_allowed: status === "canceled",
    progress: {
      phase: "downloading",
      received_bytes: 1024 ** 3,
      expected_bytes: recipe.download_bytes,
    },
  };
}
function mount({
  ready = false,
  cpu = false,
  admin = true,
  rows = [] as ReturnType<typeof preparation>[],
} = {}) {
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  const readiness = vi.fn();
  let history = rows;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push({ url, body: JSON.parse(String(init.body)) });
        history = [
          preparation(url.endsWith("/cancel") ? "canceled" : "queued"),
        ];
        if (url.endsWith("/resume"))
          history[0] = {
            ...history[0],
            attempt: 2,
            run: { ...history[0].run, id: "next-run" },
          };
        return { ok: true, json: async () => history[0] };
      }
      return {
        ok: true,
        json: async () =>
          url.split("?")[0].endsWith("/setup/runtimes")
            ? {
                recipe: cpu
                  ? {
                      ...recipe,
                      profile: "llamacpp-cpu-linux-amd64-v1",
                      cuda_license_url: undefined,
                    }
                  : recipe,
                manifest_sha256: "b".repeat(64),
                can_prepare: admin,
                usable_image: ready,
                installation_available: true,
                storage: {
                  free_bytes: 30 * 1024 ** 3,
                  required_bytes: 12 * 1024 ** 3,
                },
              }
            : history,
      };
    }),
  );
  render(
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
        <RuntimeSetupPanel
          profile={cpu ? "llamacpp-cpu-linux-amd64-v1" : undefined}
          onReadiness={readiness}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { writes, readiness };
}

it("requires license acceptance and submits only a pinned profile receipt", async () => {
  const { writes, readiness } = mount();
  const button = await screen.findByRole("button", {
    name: "Prepare llama.cpp",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(
    await screen.findByText(/30.00 GiB free in runtime storage/),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I have reviewed the runtime/ }),
  );
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Stop runtime preparation" });
  expect(writes).toHaveLength(1);
  expect(writes[0].body).toMatchObject({
    profile: recipe.profile,
    manifest_sha256: "b".repeat(64),
    license_accepted: true,
  });
  expect(writes[0].body.client_request_id).toBeTruthy();
  expect(writes[0].body.image_reference).toBeUndefined();
  expect(writes[0].body.command).toBeUndefined();
  expect(readiness).toHaveBeenCalledWith(false);
});

it("restores progress, stops, and resumes the same task with an expected-attempt receipt", async () => {
  const { writes } = mount({ rows: [preparation("running")] });
  expect(
    await screen.findByRole("progressbar", {
      name: "Runtime preparation progress",
    }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Prepare llama.cpp" }),
  ).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Stop runtime preparation" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Resume runtime preparation" }),
  );
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1].body.expected_run_id).toBe("runtime-run");
  expect(writes[1].body.client_request_id).toBeTruthy();
});

it("uses existing images without offering an unnecessary replacement download", async () => {
  const { writes, readiness } = mount({ ready: true });
  expect(await screen.findByText("Image available")).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Prepare llama.cpp" }),
  ).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(readiness).toHaveBeenCalledWith(true);
  expect(writes).toEqual([]);
});

it("keeps shared runtime mutation restricted to the administrator", async () => {
  const { writes } = mount({ admin: false });
  expect(
    await screen.findByText(/Your administrator prepares shared runtimes/),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Prepare llama.cpp" }),
  ).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(writes).toEqual([]);
});

it("prepares the explicit CPU engine without CUDA terms or a GPU readiness shortcut", async () => {
  const { writes } = mount({ cpu: true });
  expect(
    await screen.findByText(/CPU execution · no NVIDIA GPU needed/),
  ).toBeTruthy();
  expect(
    screen.queryByRole("link", { name: "CUDA component terms" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Prepare llama.cpp" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body.profile).toBe("llamacpp-cpu-linux-amd64-v1");
});
