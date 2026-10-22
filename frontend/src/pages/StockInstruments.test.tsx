import { useState, type ReactElement } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import StockInstruments from "./StockInstruments";
import AgentMarketScope from "./AgentMarketScope";
import { StockFeedConnectors } from "./StockFeedConnectors";
import { DEFAULT_MARKET, type MarketScope } from "./marketScope";
import { activationBlock } from "./agentActivation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const account = {
  id: "stocks-one",
  name: "My Finnhub",
  kind: "market_data",
  market_provider: "finnhub" as const,
  enabled: true,
  secret_present: true,
  market_policy_revision: "a".repeat(64),
  status: "unconfigured",
  health: "unknown",
  updated_at: "now",
  last_run_id: null,
};
const stock: MarketScope = {
  ...DEFAULT_MARKET,
  provider: "finnhub",
  instruments: [],
  comparison_window_seconds: 604800,
  feed: {
    connector_id: account.id,
    connector_revision: account.market_policy_revision,
  },
};
function mount(element: ReactElement) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>,
  );
}
function Picker({ initial = stock }: { initial?: MarketScope }) {
  const [value, setValue] = useState(initial);
  return <StockInstruments value={value} onChange={setValue} />;
}

it("uses an explicit queued lookup, selects and removes symbols, and never searches while typing", async () => {
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      path.endsWith("/connectors")
        ? [account]
        : options?.method === "POST"
          ? { id: "lookup-one", status: "queued" }
          : {
              id: "lookup-one",
              status: "succeeded",
              metadata: {
                market_feed: {
                  query: "Apple",
                  source_url: "https://finnhub.io",
                  fetched_at: "now",
                  truncated: false,
                  symbols: [
                    { symbol: "AAPL", name: "Apple Inc", type: "Common Stock" },
                  ],
                },
              },
            },
  }));
  vi.stubGlobal("fetch", fetcher);
  mount(<Picker />);
  await screen.findByRole("option", { name: "My Finnhub" });
  fireEvent.change(screen.getByLabelText("Find a company or symbol"), {
    target: { value: "Apple" },
  });
  expect(fetcher.mock.calls.every(([, options]) => !options?.method)).toBe(
    true,
  );
  fireEvent.click(screen.getByRole("button", { name: "Find symbols" }));
  await screen.findByText("Apple Inc");
  const sent = fetcher.mock.calls.find(
    ([, options]) => options?.method === "POST",
  );
  expect(sent?.[0]).toBe("/api/market-feeds/stocks-one/search");
  expect(JSON.parse(String(sent?.[1]?.body))).toEqual({
    query: "Apple",
    connector_revision: account.market_policy_revision,
  });
  fireEvent.click(screen.getByRole("button", { name: "Add AAPL" }));
  expect(
    screen.getByRole("button", { name: "Add AAPL" }).matches(":disabled"),
  ).toBe(true);
  expect(screen.getByText(/1 \/ 3 stocks/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Remove AAPL" }));
  expect(screen.getByText(/0 \/ 3 stocks/)).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Inspect symbol lookup" })
      .getAttribute("href"),
  ).toBe("/runs/lookup-one");
});

it("requires explicit review of a rotated account before lookup", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => [account] })),
  );
  mount(
    <Picker
      initial={{
        ...stock,
        feed: { connector_id: account.id, connector_revision: "b".repeat(64) },
      }}
    />,
  );
  await screen.findByText(/Account settings changed/);
  fireEvent.change(screen.getByLabelText("Find a company or symbol"), {
    target: { value: "Apple" },
  });
  expect(
    screen.getByRole("button", { name: "Find symbols" }).matches(":disabled"),
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("button", { name: "Use current account settings" }),
  );
  expect(
    screen.getByRole("button", { name: "Find symbols" }).matches(":disabled"),
  ).toBe(false);
  expect(
    vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method),
  ).toBe(true);
});

it("shows a configuration link without a fake working data source", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => [] })),
  );
  mount(<Picker initial={{ ...stock, feed: null }} />);
  expect(
    await screen.findByRole("link", { name: "Settings → Integrations" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Find symbols" }).matches(":disabled"),
  ).toBe(true);
});

it("supports reviewed manual symbols with a three-stock limit and no network request", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => [account] })),
  );
  mount(<Picker initial={{ ...stock, instruments: ["AAPL", "MSFT"] }} />);
  await screen.findByRole("option", { name: "My Finnhub" });
  fireEvent.change(screen.getByLabelText("Stock symbol"), {
    target: { value: "brk.b" },
  });
  fireEvent.keyDown(screen.getByLabelText("Stock symbol"), { key: "Enter" });
  expect(screen.getByText(/3 \/ 3 stocks/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Stock symbol"), {
    target: { value: "NVDA" },
  });
  expect(
    screen.getByRole("button", { name: "Add symbol" }).matches(":disabled"),
  ).toBe(true);
  expect(
    vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method),
  ).toBe(true);
});

it("switches from crypto to a disabled reviewable stock scope without inventing a company", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => [] })),
  );
  const change = vi.fn();
  mount(<AgentMarketScope value={DEFAULT_MARKET} onChange={change} />);
  fireEvent.change(screen.getByLabelText("Price source"), {
    target: { value: "finnhub" },
  });
  expect(change).toHaveBeenCalledWith({
    ...DEFAULT_MARKET,
    provider: "finnhub",
    feed: null,
    instruments: [],
    comparison_window_seconds: 604800,
  });
  const draft = {
    enabled: false,
    tools: ["market_watch"],
    market: { ...stock, instruments: ["AAPL"], feed: null },
  };
  const catalog = [
    {
      name: "market_watch",
      description: "Price watch",
      operational: true,
      required_permissions: ["network_read"],
    },
  ];
  expect(activationBlock(draft, catalog).blocked).toBe(true);
  expect(
    activationBlock(
      {
        ...draft,
        market: { ...stock, instruments: ["AAPL"] },
        market_readiness: { ready: false, reason: "Review account" },
      },
      catalog,
    ),
  ).toEqual({ blocked: true, reason: "Review account" });
});

it("keeps a saved API key write-only and saving makes no account request", async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => account }));
  vi.stubGlobal("fetch", fetcher);
  mount(<StockFeedConnectors rows={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Connect stock data" }));
  const key = screen.getByLabelText("Finnhub API key") as HTMLInputElement;
  expect(key.type).toBe("password");
  fireEvent.change(key, { target: { value: "private-fixture-stock-key" } });
  fireEvent.click(
    screen.getByRole("button", { name: "Save stock-data account" }),
  );
  await waitFor(() =>
    expect(screen.queryByLabelText("Finnhub API key")).toBeNull(),
  );
  expect(fetcher.mock.calls).toHaveLength(1);
  expect(document.body.textContent).not.toContain("private-fixture-stock-key");
});

it("freezes the settings version the operator actually opened when the account refreshes", async () => {
  const fetcher = vi.fn(async (_path: string, _options?: RequestInit) => ({
    ok: true,
    json: async () => account,
  }));
  vi.stubGlobal("fetch", fetcher);
  function RefreshedAccount() {
    const [row, setRow] = useState(account);
    return (
      <>
        <StockFeedConnectors rows={[row]} />
        <button
          onClick={() =>
            setRow({ ...row, updated_at: "later", name: "Changed elsewhere" })
          }
        >
          Refresh account fixture
        </button>
      </>
    );
  }
  mount(<RefreshedAccount />);
  fireEvent.click(screen.getByRole("button", { name: "Account settings" }));
  fireEvent.change(screen.getByLabelText("Account name"), {
    target: { value: "My edited name" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Refresh account fixture" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Save stock-data account" }),
  );
  await waitFor(() => expect(fetcher).toHaveBeenCalled());
  const sent = fetcher.mock.calls.find(
    ([, options]) => options?.method === "PATCH",
  );
  expect(JSON.parse(String(sent?.[1]?.body))).toMatchObject({
    expected_updated_at: "now",
    name: "My edited name",
  });
});
