import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AgentMarketScope, { AgentMarketEditor } from "./AgentMarketScope";
import { DEFAULT_MARKET } from "./marketScope";
import { activationBlock } from "./agentActivation";
import { agentSettingsPayload } from "./agentSettings";

afterEach(cleanup);

const catalog = [
  {
    name: "market_watch",
    description: "Price watch",
    operational: true,
    required_permissions: ["network_read"],
  },
];

describe("reviewed market watch", () => {
  it("exposes the price scope without email, trading or a model picker", () => {
    const change = vi.fn();
    render(<AgentMarketScope value={DEFAULT_MARKET} onChange={change} />);
    expect(screen.getByText(/without a model or GPU/)).toBeTruthy();
    expect(
      (screen.getByLabelText("BTC / USD") as HTMLInputElement).checked,
    ).toBe(true);
    expect(screen.getByLabelText("BTC / USD").matches(":disabled")).toBe(true);
    fireEvent.click(screen.getByLabelText("ETH / EUR"));
    expect(change).toHaveBeenCalledWith({
      ...DEFAULT_MARKET,
      instruments: ["BTC-USD", "ETH-EUR"],
    });
    expect(screen.queryByRole("button", { name: /model/i })).toBeNull();
  });

  it("edits the saved policy locally and sends it only on explicit Save", () => {
    const save = vi.fn();
    render(<AgentMarketEditor value={DEFAULT_MARKET} onSave={save} />);
    expect(
      screen
        .getByRole("button", { name: "Save price watch" })
        .matches(":disabled"),
    ).toBe(true);
    fireEvent.change(screen.getByLabelText("Alert when change reaches (%)"), {
      target: { value: "3.5" },
    });
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save price watch" }));
    expect(save).toHaveBeenCalledWith({
      ...DEFAULT_MARKET,
      threshold_percent: "3.5",
    });
  });

  it("does not submit an empty threshold or a fractional observation window", () => {
    render(<AgentMarketEditor value={DEFAULT_MARKET} onSave={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Alert when change reaches (%)"), {
      target: { value: "" },
    });
    expect(
      screen
        .getByRole("button", { name: "Save price watch" })
        .matches(":disabled"),
    ).toBe(true);
  });

  it("keeps controls disabled while an agent is active", () => {
    render(
      <AgentMarketEditor value={DEFAULT_MARKET} disabled onSave={vi.fn()} />,
    );
    expect(screen.getByLabelText("Direction").matches(":disabled")).toBe(true);
    expect(screen.getByLabelText("ETH / USD").matches(":disabled")).toBe(true);
  });

  it("allows activation without a model only for an exclusive reviewed watch", () => {
    expect(
      activationBlock(
        {
          enabled: false,
          tools: ["market_watch"],
          market: DEFAULT_MARKET,
          model: "",
        },
        catalog,
      ),
    ).toEqual({ blocked: false, reason: null });
    expect(
      activationBlock(
        { enabled: false, tools: ["market_watch"], model: "" },
        catalog,
      ).blocked,
    ).toBe(true);
    expect(
      activationBlock(
        {
          enabled: false,
          tools: ["market_watch", "http_fetch"],
          market: DEFAULT_MARKET,
        },
        catalog,
      ).blocked,
    ).toBe(true);
  });

  it("preserves reviewed scope across unrelated settings and clears it when tools change", () => {
    const agent = {
      updated_at: "now",
      name: "BTC",
      tools: ["market_watch"],
      market: { ...DEFAULT_MARKET, threshold_percent: "3" },
    };
    expect(agentSettingsPayload(agent, { description: "New" }).market).toEqual(
      agent.market,
    );
    expect(
      agentSettingsPayload(agent, { tools: ["system_snapshot"] }).market,
    ).toBeNull();
  });
});
