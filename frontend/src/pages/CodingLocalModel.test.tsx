import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { useState } from "react";
import CodingLocalModel from "./CodingLocalModel";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("keeps Auto when the model picker is canceled and performs no workload on selection", async () => {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    expect(init?.method).not.toBe("POST");
    return {
      ok: true,
      json: async () =>
        url.includes("/auto-model")
          ? {
              available: true,
              name: "Coder 27B",
              context_size: 131072,
              context_verified: true,
              reason: "Observed",
            }
          : url.endsWith("/llama")
            ? {
                models: [
                  {
                    id: "gguf",
                    name: "Coder 27B",
                    model_key: "llamacpp:gguf",
                    size_bytes: 1000,
                  },
                ],
                instances: [],
              }
            : { gpus: [] },
    };
  });
  vi.stubGlobal("fetch", fetch);
  function Form() {
    const [value, setValue] = useState("auto");
    return (
      <>
        <output data-testid="selection">{value}</output>
        <CodingLocalModel
          value={value}
          models={[]}
          busy={false}
          onSelect={setValue}
          onBusy={() => {}}
        />
      </>
    );
  }
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Form />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText(/Coder 27B · 131,072 tokens/);
  fireEvent.click(screen.getByRole("button", { name: "Choose a model" }));
  fireEvent.click(screen.getByRole("button", { name: "Close model picker" }));
  expect(screen.getByTestId("selection").textContent).toBe("auto");
  fireEvent.click(screen.getByRole("button", { name: "Choose a model" }));
  fireEvent.click(
    await screen.findByRole("button", { name: /Coder 27B, llama.cpp/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Use model" }));
  expect(screen.getByTestId("selection").textContent).toBe("llamacpp:gguf");
});
