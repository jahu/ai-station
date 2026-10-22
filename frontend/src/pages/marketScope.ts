export type MarketScope = {
  provider: "coinbase_exchange" | "finnhub";
  feed?: { connector_id: string; connector_revision: string } | null;
  instruments: string[];
  threshold_percent: string;
  direction: "both" | "up" | "down";
  comparison_window_seconds: number;
  cooldown_seconds: number;
  email?: {
    connector_id: string;
    connector_revision: string;
    recipients: string[];
  } | null;
};
export const DEFAULT_MARKET: MarketScope = {
  provider: "coinbase_exchange",
  instruments: ["BTC-USD"],
  threshold_percent: "5",
  direction: "both",
  comparison_window_seconds: 172800,
  cooldown_seconds: 3600,
};

export const marketEmailConsentKey = (
  id: string,
  market?: MarketScope | null,
) => `${id}:${JSON.stringify(market)}`;
