export type MarketScope = {
  provider: "coinbase_exchange";
  instruments: string[];
  threshold_percent: string;
  direction: "both" | "up" | "down";
  comparison_window_seconds: number;
  cooldown_seconds: number;
};
export const DEFAULT_MARKET: MarketScope = {
  provider: "coinbase_exchange",
  instruments: ["BTC-USD"],
  threshold_percent: "5",
  direction: "both",
  comparison_window_seconds: 86400,
  cooldown_seconds: 3600,
};
