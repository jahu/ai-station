import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Clapperboard, Download, Square } from "lucide-react";
import { api, type Artifact, type Run } from "../api";
import { useAccount } from "../account-context";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { creativeJson } from "../components/creative/creative-project";
import { randomId } from "../lib/random-id";
import { materialBase, type StudioRevision } from "./studio-material";
import { terminal, useStudioRenderer } from "./studio-production";

type Production = {
  root_run: Run;
  status: string;
  runs: Run[];
  output: Artifact | null;
  failed_run: Run | null;
  measured_revision_id: string;
};
export default function StudioProduction({
  materialId,
  revision,
  disabled,
  selectedTakes,
  onVersion,
}: {
  materialId: string;
  revision: StudioRevision;
  disabled: boolean;
  selectedTakes: Record<number, string>;
  onVersion: (id: string) => Promise<unknown>;
}) {
  const { user } = useAccount();
  const cache = useQueryClient();
  const key = ["studio-material-productions", user?.id, materialId];
  const values = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      api<Production[]>(`${materialBase}/${materialId}/productions`, {
        signal,
      }),
    refetchInterval: (q) =>
      q.state.data?.some(
        (p) =>
          !terminal.has(p.status) ||
          p.runs.some((r) => !terminal.has(r.status)),
      )
        ? 1500
        : false,
  });
  const renderer = useStudioRenderer();
  const current = values.data?.find(
    (p) =>
      p.root_run.parameters.studio_revision_id === revision.id ||
      p.measured_revision_id === revision.id,
  );
  const active = values.data?.find(
    (p) =>
      !terminal.has(p.status) || p.runs.some((r) => !terminal.has(r.status)),
  );
  const receipt = useRef<{ fingerprint: string; id: string } | null>(null);
  function refresh() {
    void cache.invalidateQueries({ queryKey: key });
    for (const queryKey of [
      ["studio-activity", user?.id, materialId],
      ["studio-production", user?.id, materialId],
      ["studio-audio-productions", user?.id, materialId],
      ["studio-exports", user?.id, materialId],
    ])
      void cache.invalidateQueries({ queryKey });
  }
  const action = useMutation({
    mutationFn: (kind: "produce" | "retry" | "stop") => {
      if (kind === "stop" && active)
        return api(
          `${materialBase}/${materialId}/productions/${active.root_run.id}/stop`,
          creativeJson("POST", {}),
        );
      if (kind === "retry" && current) {
        const previous = current.root_run.parameters.request as Record<
          string,
          unknown
        >;
        const body: Record<string, unknown> = {
          ...previous,
          reuse_from_run_id: current.root_run.id,
        };
        delete body.client_request_id;
        const fingerprint = JSON.stringify(body);
        if (receipt.current?.fingerprint !== fingerprint)
          receipt.current = { fingerprint, id: randomId() };
        return api(
          `${materialBase}/${materialId}/produce`,
          creativeJson("POST", {
            ...body,
            client_request_id: receipt.current.id,
          }),
        );
      }
      const body = {
        revision_id: revision.id,
        bindings: Object.entries(selectedTakes).map(([scene, artifact_id]) => ({
          scene: Number(scene),
          artifact_id,
        })),
      };
      const fingerprint = JSON.stringify(body);
      if (receipt.current?.fingerprint !== fingerprint)
        receipt.current = { fingerprint, id: randomId() };
      return api(
        `${materialBase}/${materialId}/produce`,
        creativeJson("POST", {
          ...body,
          client_request_id: receipt.current.id,
        }),
      );
    },
    onSuccess: () => {
      receipt.current = null;
      refresh();
    },
  });
  return (
    <section
      className="studio-film-production"
      aria-label="Complete film production"
    >
      <header>
        <div>
          <span className="studio-eyebrow">FROM PLAN TO FILM</span>
          <h3>
            {current?.output
              ? "Your film is ready"
              : "Bring the whole story to life"}
          </h3>
          <p>
            Produce the complete saved story: sound first, shots timed to the
            narration, then a Full-HD film. Completed takes are kept.
          </p>
        </div>
        <Clapperboard size={24} />
      </header>
      <ol className="studio-film-stages">
        <li>
          <span>01</span> Sound & timing
        </li>
        <li>
          <span>02</span> Visuals & footage
        </li>
        <li>
          <span>03</span> Final film
        </li>
      </ol>
      {active && (
        <div className="studio-export-progress" role="status">
          <div>
            <strong>Producing your film</strong>
            <span>
              Your saved plan and selected takes are frozen for this production.
            </span>
          </div>
          <Badge status={active.status} />
          <Button
            type="button"
            variant="secondary"
            disabled={action.isPending}
            onClick={() => action.mutate("stop")}
          >
            <Square size={14} /> Stop production
          </Button>
        </div>
      )}
      {current?.output && (
        <div className="studio-export-result">
          <video
            controls
            playsInline
            preload="metadata"
            aria-label="Produced film"
            src={`/api/artifacts/${current.output.id}/file`}
          />
          <div>
            <Link to={`/library/${current.output.id}`}>
              Open finished film ↗
            </Link>
            <a
              href={`/api/artifacts/${current.output.id}/file`}
              download={current.output.original_filename}
            >
              <Download size={15} /> Download MP4
            </a>
          </div>
        </div>
      )}
      {current &&
        terminal.has(current.status) &&
        current.status !== "succeeded" && (
          <p className="notice" role="alert">
            {current.failed_run?.error_message ||
              "Production stopped before the finished film. Completed media are kept."}
          </p>
        )}
      {!active && (
        <div className="studio-film-actions">
          <Button
            type="button"
            disabled={disabled || action.isPending || !renderer.data?.available}
            onClick={() => action.mutate("produce")}
          >
            <Clapperboard size={15} />{" "}
            {current?.output ? "Produce another film" : "Produce film"}
          </Button>
          {current &&
            ["failed", "interrupted", "canceled"].includes(current.status) && (
              <Button
                type="button"
                variant="secondary"
                disabled={
                  disabled || action.isPending || !renderer.data?.available
                }
                onClick={() => action.mutate("retry")}
              >
                Continue · reuse completed media
              </Button>
            )}
          {current?.output && current.measured_revision_id !== revision.id && (
            <Button
              type="button"
              variant="ghost"
              disabled={disabled}
              onClick={() => void onVersion(current.measured_revision_id)}
            >
              Open measured edit
            </Button>
          )}
        </div>
      )}
      {disabled && (
        <p className="studio-direction-note">
          Production uses a saved, active version. Save edits or restore the
          material to continue.
        </p>
      )}
      {!renderer.isPending && !renderer.data?.available && (
        <p className="studio-direction-note">
          {renderer.data?.readiness === "checking"
            ? "Checking local film export…"
            : "Prepare film export below before starting. This avoids generating media for an unavailable exporter."}
        </p>
      )}
      {current && (
        <details>
          <summary>Production details</summary>
          <p className="studio-direction-note">
            <Badge status={current.status} /> · {current.runs.length} recorded
            Runs ·{" "}
            <Link to={`/runs/${current.root_run.id}`}>Inspect production</Link>
          </p>
          <p className="studio-direction-note">
            Use the soundtrack and shot controls below for individual changes.
            Each production keeps its original saved version.
          </p>
        </details>
      )}
      <ErrorNotice error={values.error ?? renderer.error ?? action.error} />
    </section>
  );
}
