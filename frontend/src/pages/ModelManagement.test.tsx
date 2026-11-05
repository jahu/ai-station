import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { AccountContext } from "../account-context";
import { Models } from "./Models";
import ModelDiscover from "./ModelDiscover";
import ModelSetup from "./ModelSetup";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function HistoryBack() {
  const navigate = useNavigate();
  return <button onClick={() => navigate(-1)}>Browser back</button>;
}
function mount(path = "/models", admin = true) {
  const writes: string[] = [];
  const reads: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") writes.push(url);
      else reads.push(url);
      return {
        ok: true,
        json: async () =>
          init?.method === "POST"
            ? { id: "inspection" }
            : url === "/api/runs/inspection"
              ? {
                  id: "inspection",
                  executor_type: "model_hub_inspect",
                  status: "succeeded",
                  metadata: {},
                }
              : url === "/api/setup/catalog"
                ? {
                    entries: [],
                    hardware: { memory: { total_mib: 32768 }, gpus: [] },
                  }
                : url.includes("preparations") || url === "/api/setup/downloads"
                  ? []
                  : { items: [], total: 0, latest_scan: null },
      };
    }),
  );
  render(
    <AccountContext.Provider value={{ mode: admin ? "operator" : "accounts" }}>
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <MemoryRouter initialEntries={[path]}>
          <HistoryBack />
          <Routes>
            <Route path="/models" element={<Models />} />
            <Route path="/models/discover" element={<ModelDiscover />} />
            <Route path="/setup/models" element={<ModelSetup />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </AccountContext.Provider>,
  );
  return { reads, writes };
}

it("makes adding a model the primary action and waits for an explicit search", async () => {
  const { writes } = mount();
  fireEvent.click(await screen.findByRole("link", { name: "Add model" }));
  await screen.findByRole("heading", { name: "Add a model" });
  expect(writes).toEqual([]);
  expect(
    screen
      .getByRole("link", { name: "Browse & download" })
      .getAttribute("aria-current"),
  ).toBe("page");
  fireEvent.change(screen.getByLabelText("Model name or Hugging Face link"), {
    target: { value: "publisher/model" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Check model" }));
  await screen.findByText("Source reviewed");
  expect(writes).toEqual(["/api/model-hub/inspections"]);
  expect(
    screen
      .getByRole("list", { name: "Add model progress" })
      .querySelector('[aria-current="step"]')?.textContent,
  ).toContain("Choose a model");
});

it("offers obvious setup and download cards without conflating a folder scan with a download", async () => {
  const { writes } = mount();
  const actions = await screen.findByRole("region", { name: "Add models" });
  expect(
    within(actions)
      .getByRole("link", { name: /Find & download models/ })
      .getAttribute("href"),
  ).toBe("/models/discover");
  fireEvent.click(
    within(actions).getByRole("link", { name: /Set up your first model/ }),
  );
  await screen.findByRole("heading", { name: "Quick setup" });
  expect(writes).toEqual([]);
});

it("keeps non-administrator discovery and scan controls hidden", async () => {
  mount("/models", false);
  await screen.findByRole("heading", { name: "On this station" });
  expect(screen.queryByRole("link", { name: "Add model" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Browse & download" })).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Scan local folders" }),
  ).toBeNull();
  expect(screen.getByRole("link", { name: "Quick setup" })).toBeTruthy();
});

it("opens a media deep link directly and switches categories with browser history", async () => {
  const { reads, writes } = mount("/setup/models?capability=images");
  await screen.findByRole("heading", { name: "Images & photo editing" });
  expect(
    screen.queryByRole("heading", { name: "Start with a conversation model" }),
  ).toBeNull();
  const categories = screen.getByRole("navigation", { name: "Setup category" });
  expect(
    within(categories)
      .getByRole("link", { name: "Images" })
      .getAttribute("aria-current"),
  ).toBe("page");
  fireEvent.click(within(categories).getByRole("link", { name: "Memory" }));
  await screen.findByRole("heading", { name: "Memory & search" });
  expect(
    screen.queryByRole("heading", { name: "Images & photo editing" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  await screen.findByRole("heading", { name: "Images & photo editing" });
  expect(
    reads.some((url) =>
      /profile=(sonic|wan22|ace-step|chatterbox|fish)/.test(url),
    ),
  ).toBe(false);
  expect(writes).toEqual([]);
});

it("preserves the existing Fish voice deep link", async () => {
  mount("/setup/models?capability=fish");
  await screen.findByRole("heading", { name: "Expressive voice & delivery" });
  expect(
    within(screen.getByRole("navigation", { name: "Setup category" }))
      .getByRole("link", { name: "Voice" })
      .getAttribute("aria-current"),
  ).toBe("page");
});

it("falls back to conversation setup for an unsupported category", async () => {
  const { writes } = mount("/setup/models?capability=unknown");
  await screen.findByRole("heading", {
    name: "Start with a conversation model",
  });
  expect(writes).toEqual([]);
});
