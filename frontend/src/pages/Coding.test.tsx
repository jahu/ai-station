import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Coding from "./Coding";

function chooseExecutor(name: string) {
  const key = name === "Local AI" ? "local" : name.toLowerCase();
  fireEvent.click(
    screen
      .getByLabelText(`Executor ${key}`)
      .querySelector("input") as HTMLElement,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it.each(["Cursor", "Codex", "Local AI"])(
  "starts %s with automatic file discovery and a persistent conversation",
  async (executor) => {
    const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
      ok: true,
      json: async () =>
        options?.method === "POST"
          ? { id: "prepare", task_id: "conversation" }
          : path.includes("/coding/models/")
            ? {
                models: [{ id: "available-model", name: "Available model" }],
                notice: "",
              }
            : path.endsWith("/sessions")
              ? []
              : path.endsWith("/provider")
                ? { models: ["local-model"], default_model: "local-model" }
                : path.endsWith("/llama")
                  ? {
                      models: [
                        {
                          id: "gguf",
                          name: "27B Uncensored",
                          model_key: "llamacpp:gguf",
                          size_bytes: 16000000000,
                        },
                      ],
                      instances: [
                        {
                          id: "runtime",
                          status: "stopped",
                          metadata: { model_file_id: "gguf", gpus: [0, 1] },
                        },
                      ],
                    }
                  : path.endsWith("/hardware")
                    ? { gpus: [] }
                    : [
                        {
                          id: "project",
                          name: "Example",
                          updated_at: "version",
                          preferred_executor: "cursor",
                        },
                      ],
    }));
    vi.stubGlobal("fetch", fetch);
    const cache = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={cache}>
        <MemoryRouter initialEntries={["/coding"]}>
          <Routes>
            <Route path="/coding" element={<Coding />} />
            <Route
              path="/coding/conversation"
              element={<h1>Coding conversation</h1>}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(
      (await screen.findByLabelText("Project project")).querySelector(
        "input",
      ) as HTMLElement,
    );
    fireEvent.change(screen.getByLabelText("Task"), {
      target: { value: "Build my idea" },
    });
    chooseExecutor(executor);
    expect(screen.queryByLabelText("Files the agent may edit")).toBeNull();
    if (executor !== "Local AI") {
      await screen.findByLabelText("Model available-model");
      expect(
        (
          screen
            .getByLabelText("Model auto")
            .querySelector("input") as HTMLInputElement
        ).checked,
      ).toBe(true);
      const button = screen.getByRole("button", { name: "Start coding" });
      expect((button as HTMLButtonElement).disabled).toBe(true);
      fireEvent.click(
        screen.getByRole("checkbox", { name: /Allow .* to receive/ }),
      );
      act(() =>
        cache.setQueryData(
          ["coding-projects"],
          [
            {
              id: "project",
              name: "Example",
              updated_at: "changed",
              preferred_executor: "codex",
            },
          ],
        ),
      );
      await vi.waitFor(() =>
        expect(
          (
            screen.getByRole("checkbox", {
              name: /Allow .* to receive/,
            }) as HTMLInputElement
          ).checked,
        ).toBe(false),
      );
      const other = executor === "Cursor" ? "Codex" : "Cursor";
      chooseExecutor(other);
      expect(
        (
          screen.getByRole("checkbox", {
            name: /Allow .* to receive/,
          }) as HTMLInputElement
        ).checked,
      ).toBe(false);
      chooseExecutor(executor);
      fireEvent.click(
        screen
          .getByLabelText("Model available-model")
          .querySelector("input") as HTMLElement,
      );
      fireEvent.click(
        screen.getByRole("checkbox", { name: /Allow .* to receive/ }),
      );
    } else {
      expect(
        screen.getByText(/Public URLs in the task are fetched automatically/),
      ).toBeTruthy();
      fireEvent.click(await screen.findByRole("button", { name: "Model" }));
      await screen.findByRole("button", { name: "local-model, local server" });
      fireEvent.click(
        await screen.findByRole("button", {
          name: /27B Uncensored, llama.cpp/,
        }),
      );
      fireEvent.click(screen.getByRole("button", { name: "Use model" }));
      expect(
        screen.getByRole("button", { name: "Model" }).textContent,
      ).toContain("27B Uncensored");
    }
    expect(
      screen.getByText(/replace a unique snippet; it cannot delete files/),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start coding" }));
    await screen.findByRole("heading", { name: "Coding conversation" });
    const call = fetch.mock.calls.find(
      ([path, options]) =>
        path.startsWith("/api/coding/") && options?.method === "POST",
    )!;
    expect(call[0]).toBe(
      `/api/coding/${executor === "Local AI" ? "local" : executor.toLowerCase()}`,
    );
    expect(JSON.parse(call[1]!.body as string)).toMatchObject({
      project_id: "project",
      files: [],
      explore: true,
      model: executor === "Local AI" ? "llamacpp:gguf" : "available-model",
      ...(executor === "Local AI" ? { max_repair_attempts: 0 } : {}),
    });
    if (executor !== "Local AI") {
      expect(
        JSON.parse(call[1]!.body as string).max_repair_attempts,
      ).toBeUndefined();
    }
  },
);

it("posts a selected local repair budget from the coding start form", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method === "POST"
        ? { id: "prepare", task_id: "conversation" }
        : path.endsWith("/sessions")
          ? []
          : path.endsWith("/provider")
            ? { models: ["local-model"], default_model: "local-model" }
            : path.endsWith("/llama")
              ? { models: [], instances: [] }
              : path.endsWith("/hardware")
                ? { gpus: [] }
                : [
                    {
                      id: "project",
                      name: "Example",
                      updated_at: "version",
                      preferred_executor: "local",
                    },
                  ],
  }));
  vi.stubGlobal("fetch", fetch);
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={["/coding"]}>
        <Routes>
          <Route path="/coding" element={<Coding />} />
          <Route
            path="/coding/conversation"
            element={<h1>Coding conversation</h1>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(
    (await screen.findByLabelText("Project project")).querySelector(
      "input",
    ) as HTMLElement,
  );
  fireEvent.change(screen.getByLabelText("Task"), {
    target: { value: "Build my idea" },
  });
  chooseExecutor("Local AI");
  const repairList = (await screen.findByLabelText("Repair 0")).closest(
    ".repair-choice-list",
  ) as HTMLElement;
  fireEvent.keyDown(repairList, { key: "End" });
  fireEvent.keyDown(repairList, { key: "Enter" });
  fireEvent.click(screen.getByRole("button", { name: "Start coding" }));
  await screen.findByRole("heading", { name: "Coding conversation" });
  const call = fetch.mock.calls.find(
    ([path, options]) =>
      path === "/api/coding/local" && options?.method === "POST",
  )!;
  expect(JSON.parse(call[1]!.body as string).max_repair_attempts).toBe(2);
});
