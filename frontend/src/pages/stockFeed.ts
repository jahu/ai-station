export type StockFeed = {
  id: string;
  name: string;
  kind: string;
  market_provider?: "finnhub";
  market_policy_revision?: string;
  enabled: boolean;
  status: string;
  health: string;
  updated_at: string;
  last_run_id: string | null;
  secret_present: boolean;
};
export const stockTerminal = new Set([
  "succeeded",
  "failed",
  "canceled",
  "interrupted",
]);
export const stockJson = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
