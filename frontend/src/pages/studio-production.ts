import { useQuery } from "@tanstack/react-query";
import { api, type Artifact, type Run } from "../api";
import { useAccount } from "../account-context";
import { materialBase } from "./studio-material";

export const terminal = new Set([
  "succeeded",
  "failed",
  "canceled",
  "interrupted",
]);
export type ShotProduction = { runs: Run[]; artifacts: Artifact[] };
export function useShotProduction(materialId: string, revisionId: string) {
  const { user } = useAccount();
  return useQuery({
    queryKey: ["studio-production", user?.id, materialId, revisionId],
    queryFn: ({ signal }) =>
      api<ShotProduction>(
        `${materialBase}/${materialId}/revisions/${revisionId}/production`,
        { signal },
      ),
    refetchInterval: (q) =>
      q.state.data?.runs?.some((r) => !terminal.has(r.status)) ? 1500 : false,
  });
}
