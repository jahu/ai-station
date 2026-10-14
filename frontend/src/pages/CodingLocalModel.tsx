import { useQuery } from "@tanstack/react-query";
import { Cpu } from "lucide-react";
import { api } from "../api";
import { Button } from "../components/ui/button";
import LlamaModels from "./LlamaModels";

type Selection = {
  available: boolean;
  name?: string;
  context_size?: number;
  context_verified?: boolean;
  reason: string;
};
export default function CodingLocalModel({
  value,
  models,
  busy,
  onSelect,
  onBusy,
}: {
  value: string;
  models: string[];
  busy: boolean;
  onSelect: (value: string) => void;
  onBusy: (busy: boolean) => void;
}) {
  const automatic = value === "auto";
  const preview = useQuery({
    queryKey: ["coding-auto-model"],
    queryFn: () => api<Selection>("/coding/auto-model"),
    enabled: automatic,
    staleTime: 30000,
  });
  return (
    <div className="coding-auto-model">
      {automatic ? (
        <>
          <div className="coding-auto-selection">
            <Cpu size={17} />
            <div>
              <strong>Auto · local long-context model</strong>
              <p className="muted">
                {preview.isPending
                  ? "Checking installed models…"
                  : preview.data?.available
                    ? `${preview.data.name} · ${preview.data.context_size?.toLocaleString()} tokens${preview.data.context_verified ? " · verified" : " · estimated"}`
                    : preview.data?.reason ||
                      preview.error?.message ||
                      "No qualified model available"}
              </p>
            </div>
          </div>
        </>
      ) : null}
      <LlamaModels
        coding
        selectionOnly
        value={automatic ? "" : value}
        models={models}
        busy={busy}
        onSelect={onSelect}
        onBusy={onBusy}
        triggerLabel={automatic ? "Choose a model" : "Model"}
      />
      {!automatic && (
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={() => onSelect("auto")}
        >
          Use Auto
        </Button>
      )}
    </div>
  );
}
