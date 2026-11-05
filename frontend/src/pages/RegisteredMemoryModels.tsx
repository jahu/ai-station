import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

export type MemoryModelChoice = {
  id: string;
  name: string;
  available: boolean;
  device: string;
  dimension: number;
};

export default function RegisteredMemoryModels({
  models,
  currentId,
  revision,
  canSelect,
  busy,
}: {
  models: MemoryModelChoice[];
  currentId?: string;
  revision: number;
  canSelect: boolean;
  busy: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const [choice, setChoice] = useState<string | null>(null);
  const selected = choice ?? params.get("embedding_model") ?? currentId ?? "";
  const model = models.find((item) => item.id === selected);
  const cache = useQueryClient();
  const select = useMutation({
    mutationFn: () =>
      api(`/memory/embeddings/models/${selected}/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: revision, confirm: true }),
      }),
    onSuccess: async () => {
      setChoice(null);
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          next.delete("embedding_model");
          return next;
        },
        { replace: true },
      );
      await cache.invalidateQueries({ queryKey: ["memory-embeddings"] });
    },
  });
  if (!models.length) return null;
  return (
    <div className="memory-semantic-setup">
      <label>
        Memory model
        <select
          aria-label="Memory model"
          value={selected}
          disabled={busy || select.isPending}
          onChange={(event) => setChoice(event.target.value)}
        >
          <option value="">Choose an installed encoder</option>
          {selected && !model && (
            <option value={selected} disabled>
              Saved encoder · unavailable
            </option>
          )}
          {models.map((item) => (
            <option key={item.id} value={item.id} disabled={!item.available}>
              {item.name} · CPU · F32{item.available ? "" : " · unavailable"}
            </option>
          ))}
        </select>
      </label>
      <p className="muted">
        Use an installed encoder for the station’s semantic memory. Health
        checking and indexing run locally on CPU. Switching rebuilds the index;
        saved memories stay intact.
      </p>
      <Button
        disabled={
          !canSelect ||
          busy ||
          select.isPending ||
          !model?.available ||
          selected === currentId
        }
        onClick={() => select.mutate()}
      >
        {select.isPending ? "Selecting…" : "Use for memory"}
      </Button>
      {!canSelect && (
        <p className="muted">
          An administrator can change the station’s encoder.
        </p>
      )}
      <ErrorNotice error={select.error} />
    </div>
  );
}
