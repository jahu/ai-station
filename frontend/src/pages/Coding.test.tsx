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
    fireEvent.change(await screen.findByLabelText("Project"), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getByLabelText("Task"), {
      target: { value: "Build my idea" },
    });
    fireEvent.click(screen.getByRole("button", { name: executor }));
    expect(screen.queryByLabelText("Files the agent may edit")).toBeNull();
    if (executor !== "Local AI") {
      await screen.findByRole("option", { name: "Available model" });
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
      fireEvent.click(screen.getByRole("button", { name: other }));
      expect(
        (
          screen.getByRole("checkbox", {
            name: /Allow .* to receive/,
          }) as HTMLInputElement
        ).checked,
      ).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: executor }));
      fireEvent.change(screen.getByLabelText("Model"), {
        target: { value: "available-model" },
      });
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
    });
  },
);
