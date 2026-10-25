import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import NewChat from "./NewChat";
import type { ChatProviderInfo } from "./ChatProviders";

const key = "local-openai-compatible",
  model = "llamacpp:11111111-1111-4111-8111-111111111111";
const provider = {
  key,
  enabled: true,
  builtin: true,
  location: "local",
  default_model: model,
  models: [model],
  secret_source: "none",
  secret_present: false,
} as ChatProviderInfo;
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(verified: boolean) {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push(JSON.parse(String(init.body)));
        return {
          ok: true,
          json: async () => ({ conversation_id: "accepted" }),
        };
      }
      return {
        ok: true,
        json: async () =>
          url.includes("model-catalog")
            ? {
                models: [
                  {
                    model_key: model,
                    provider_key: key,
                    model_ref: model,
                    display_name: "Local model",
                    location: "local",
                    runtime_kind: "llama.cpp",
                    availability: "ready",
                    reasoning_capability: {
                      kind: verified ? "toggle" : "unsupported",
                      verified,
                    },
                  },
                ],
                providers: [],
              }
            : url.includes("preferences")
              ? {
                  version: 0,
                  mode: "chat",
                  provider: key,
                  model,
                  send_key: "enter",
                }
              : [],
      };
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <NewChat
          providers={[provider]}
          provider={provider}
          onProviderChange={() => {}}
          onAccepted={() => {}}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return writes;
}

it("omits unsupported thinking controls", async () => {
  mount(false);
  await screen.findByRole("textbox", { name: "Message" });
  await vi.waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Change model" }).textContent,
    ).toContain("Local model"),
  );
  expect(screen.queryByRole("switch", { name: "Thinking" })).toBeNull();
});

it("sends verified thinking in the unified conversation without a mode switch", async () => {
  const writes = mount(true);
  const toggle = await screen.findByRole("switch", { name: "Thinking" });
  fireEvent.click(toggle);
  expect(toggle.getAttribute("aria-checked")).toBe("true");
  const text = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(text, { target: { value: "Explain this" } });
  expect(screen.queryByRole("group", { name: "Conversation mode" })).toBeNull();
  expect((text as HTMLTextAreaElement).value).toBe("Explain this");
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await vi.waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    reasoning: { enabled: true, budget: 256 },
    execution_mode: "assistant",
  });
});
