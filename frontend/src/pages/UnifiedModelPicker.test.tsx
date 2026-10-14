import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import UnifiedModelPicker, { type CatalogModel } from "./UnifiedModelPicker";
import NewChat from "./NewChat";
import type { ChatProviderInfo } from "./ChatProviders";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const version = "2026-10-14T12:00:00+00:00";
const gguf: CatalogModel = {
  model_ref: "llamacpp:11111111-1111-4111-8111-111111111111",
  model_key: "llamacpp:11111111-1111-4111-8111-111111111111",
  provider_key: "local-openai-compatible",
  provider_name: "Local · llama.cpp",
  display_name: "Coder 27B Q4",
  location: "local",
  runtime_kind: "llama.cpp",
  availability: "loads_when_needed",
  unavailable_reason: "",
  config_version: version,
  endpoint_host: "",
  modalities: ["text"],
};
const cloud: CatalogModel = {
  ...gguf,
  model_ref: "provider:cloud:cloud-model",
  model_key: "cloud-model",
  provider_key: "cloud",
  provider_name: "Cloud service",
  display_name: "Cloud model",
  runtime_kind: "external",
  location: "external",
  availability: "configured",
  endpoint_host: "models.example.test",
};
const catalog = {
  models: [
    gguf,
    cloud,
    {
      ...gguf,
      model_ref: "missing",
      model_key: "llamacpp:missing",
      display_name: "Missing model",
      availability: "unavailable",
      unavailable_reason: "Model file is missing",
    },
  ],
  providers: [
    {
      key: gguf.provider_key,
      name: "Local server",
      location: "local",
      enabled: true,
    },
    {
      key: "cloud",
      name: "Cloud service",
      location: "external",
      enabled: true,
    },
  ],
};
function wrap(element: React.ReactNode) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>,
  );
}

it("searches unloaded local models and selects without loading or a setup form", async () => {
  const choose = vi.fn(),
    fetch = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (url.includes("model-catalog") ? catalog : null),
    }));
  vi.stubGlobal("fetch", fetch);
  wrap(
    <UnifiedModelPicker
      providerKey={gguf.provider_key}
      modelKey="qwen"
      onSelect={choose}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Change model" }));
  const missing = await screen.findByRole("button", { name: /Missing model/ });
  expect((missing as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByRole("textbox", { name: "Search models" }), {
    target: { value: "27B" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Coder 27B/ }));
  expect(choose).toHaveBeenCalledWith(gguf);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(
    fetch.mock.calls.every(([url]) =>
      String(url).includes("/chat/model-catalog"),
    ),
  ).toBe(true);
});

it("labels external choices and queries only the provider explicitly browsed", async () => {
  const calls: string[] = [],
    choose = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      return {
        ok: true,
        json: async () =>
          url.includes("discover_provider=cloud")
            ? {
                ...catalog,
                models: [
                  ...catalog.models,
                  {
                    ...cloud,
                    model_ref: "provider:cloud:extra",
                    model_key: "extra",
                    display_name: "Extra cloud model",
                    availability: "available",
                  },
                ],
              }
            : catalog,
      };
    }),
  );
  wrap(
    <UnifiedModelPicker
      providerKey={gguf.provider_key}
      modelKey="qwen"
      onSelect={choose}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Change model" }));
  await screen.findByRole("region", { name: "External providers" });
  expect(calls.some((url) => url.includes("discover_provider"))).toBe(false);
  fireEvent.click(
    screen.getByRole("button", { name: "Browse Cloud service models" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /Extra cloud model/ }),
  );
  expect(choose.mock.calls[0][0]).toMatchObject({
    provider_key: "cloud",
    location: "external",
    model_key: "extra",
    config_version: version,
  });
  expect(
    calls
      .filter((url) => url.includes("discover_provider"))
      .every((url) => url.endsWith("discover_provider=cloud")),
  ).toBe(true);
});

it("first Send carries the exact model and provider version picked without a prior load", async () => {
  const writes: Record<string, unknown>[] = [];
  const provider = {
    key: gguf.provider_key,
    name: "Local",
    builtin: true,
    enabled: true,
    location: "local",
    default_model: "qwen",
    models: ["qwen"],
    secret_source: "none",
    secret_present: false,
  } as ChatProviderInfo;
  const accepted = vi.fn();
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
            ? catalog
            : {
                version: 0,
                mode: "chat",
                provider: provider.key,
                model: "qwen",
                send_key: "enter",
              },
      };
    }),
  );
  wrap(
    <NewChat
      providers={[provider]}
      provider={provider}
      onProviderChange={() => {}}
      onAccepted={accepted}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Change model" }));
  fireEvent.click(await screen.findByRole("button", { name: /Coder 27B/ }));
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
    target: { value: "A local question" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await vi.waitFor(() => expect(accepted).toHaveBeenCalledWith("accepted"));
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    expected_provider_version: version,
    selection: { provider: provider.key, model: gguf.model_key },
    content: "A local question",
  });
});
