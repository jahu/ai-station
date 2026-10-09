import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { GitCommitHorizontal, Check } from "lucide-react";
import { api } from "../api";
import { Button } from "../components/ui/button";
import { ErrorNotice } from "../components/common";
import Markdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import type { Run } from "../api";

type Review = {
  exploration?: {
    request: Record<string, unknown>;
    result: Record<string, unknown>;
  }[];
  branch: string;
  files: {
    path: string;
    diff: string;
    insertions: number;
    deletions: number;
  }[];
};

export default function CodingReview({
  run,
  onQueued,
}: {
  run: Run;
  onQueued?: (result: Run) => void;
}) {
  const local = run.metadata?.execution_location === "local";
  const next = run.metadata?.coding_run_id;
  const validation = run.metadata?.validation_run_id;
  const externalName =
    run.executor_type === "codex_proposal" ||
    run.metadata?.next_executor === "codex_proposal"
      ? "Codex"
      : "Cursor";
  const review = run.metadata?.coding_review as Review | undefined;
  if (
    !next &&
    !review &&
    (![
      "cursor_proposal",
      "codex_proposal",
      "local_proposal",
      "worktree_prepare",
    ].includes(run.executor_type) ||
      run.metadata?.execution_location !== "external")
  )
    return null;
  return (
    <section className="panel content-panel">
      <span className="chip">
        {local ? "LOCAL AI" : `EXTERNAL ${externalName.toUpperCase()} AI`}
      </span>
      {typeof next === "string" && (
        <p>
          <Link className="text-link" to={`/runs/${next}`}>
            Open {local ? "local coding" : externalName} execution →
          </Link>
        </p>
      )}
      {review && (
        <>
          <h2 className="mt">
            {run.metadata?.repair_run_id || run.metadata?.continuation_run_id
              ? "Previous attempt"
              : run.metadata?.review_status === "committed"
                ? "Reviewed changes committed"
                : "Changes awaiting review"}
          </h2>
          <p className="mono">{review.branch}</p>
          <p>
            Agent completion is not a correctness verdict. Review the changes
            and validation before integrating this branch. Unique snippet
            replacements and complete file rewrites both appear as ordinary
            patches. File deletion is not allowed.
          </p>
          {Number(run.parameters?.max_repair_attempts ?? 0) > 0 && (
            <p className="muted">
              Repair attempts: {Number(run.parameters?.repair_attempt ?? 0)} ·
              Automatic limit: {Number(run.parameters?.max_repair_attempts)}.
              Each attempt preserves the original model, file scope and
              validation commands.
            </p>
          )}
          {typeof validation === "string" ? (
            <ValidationActions
              run={run}
              validationId={validation}
              onQueued={onQueued}
            />
          ) : (
            <p className="notice">
              No validation commands were configured. This proposal has not been
              tested.
            </p>
          )}
          {typeof run.metadata?.repair_source_run_id === "string" && (
            <p className="muted">
              This review includes all changes from the task base, including the
              previous proposal.{" "}
              <Link
                className="text-link"
                to={`/runs/${run.metadata.repair_source_run_id}`}
              >
                Previous attempt →
              </Link>
            </p>
          )}
          {!!review.exploration?.length && (
            <details>
              <summary>
                Repository exploration · {review.exploration.length} steps
              </summary>
              <div className="coding-exploration">
                {review.exploration.map((step, i) => (
                  <article key={i}>
                    <strong>
                      {i + 1}. {String(step.request.tool)}
                    </strong>
                    <pre>{JSON.stringify(step.request, null, 2)}</pre>
                    <details>
                      <summary>Observed result</summary>
                      <pre>{JSON.stringify(step.result, null, 2)}</pre>
                    </details>
                  </article>
                ))}
              </div>
            </details>
          )}
          {!review.files.length && <p>No file contents changed.</p>}
          {review.files.map((file) => (
            <details key={file.path} open>
              <summary>
                {file.path} · +{file.insertions} / −{file.deletions}
              </summary>
              <div className="markdown">
                <Markdown
                  rehypePlugins={[rehypeHighlight]}
                  components={{
                    img: () => null,
                    a: ({ children }) => <span>{children}</span>,
                  }}
                >
                  {"````````````diff\n" + file.diff + "\n````````````"}
                </Markdown>
              </div>
            </details>
          ))}
          {review.files.length > 0 &&
            run.status === "succeeded" &&
            typeof validation !== "string" &&
            !run.metadata?.repair_run_id &&
            !run.metadata?.continuation_run_id && (
              <CommitReview run={run} onQueued={onQueued} />
            )}
        </>
      )}
    </section>
  );
}

function CommitReview({
  run,
  onQueued,
}: {
  run: Run;
  onQueued?: (result: Run) => void;
}) {
  const navigate = useNavigate();
  const [message, setMessage] = useState(
    (run.summary || "Apply reviewed changes").slice(0, 2000),
  );
  const [reviewed, setReviewed] = useState(false);
  const commit = useMutation({
    mutationFn: () =>
      api<Run>(`/coding/runs/${run.id}/commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, reviewed: true }),
      }),
    onSuccess: (result) =>
      onQueued ? onQueued(result) : navigate(`/runs/${result.id}`),
  });
  const next = run.metadata?.commit_run_id;
  if (typeof next === "string")
    return (
      <div className="content-panel">
        <p>
          <Check size={16} /> Commit request recorded
        </p>
        <Link className="text-link" to={`/runs/${next}`}>
          Inspect commit and status →
        </Link>
      </div>
    );
  return (
    <form
      className="content-panel image-form project-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (reviewed) commit.mutate();
      }}
    >
      <h3 className="row">
        <GitCommitHorizontal size={20} /> Save reviewed changes
      </h3>
      <p className="muted">
        Create a local commit on this task branch. Your active checkout stays
        untouched. Configured validation must pass.
      </p>
      <ErrorNotice error={commit.error} />
      <label>
        Commit message
        <input
          required
          maxLength={2000}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          disabled={commit.isPending}
        />
      </label>
      <label className="project-checkbox">
        <input
          type="checkbox"
          checked={reviewed}
          onChange={(event) => setReviewed(event.target.checked)}
          disabled={commit.isPending}
        />
        I reviewed the diff and validation results.
      </label>
      <Button disabled={!reviewed || !message.trim() || commit.isPending}>
        <GitCommitHorizontal size={16} />
        {commit.isPending ? "Queuing commit…" : "Commit reviewed changes"}
      </Button>
      <p className="muted">
        The commit includes only these reviewed files. Publishing and merging
        remain separate actions.
      </p>
    </form>
  );
}

function ValidationActions({
  run,
  validationId,
  onQueued,
}: {
  run: Run;
  validationId: string;
  onQueued?: (result: Run) => void;
}) {
  const navigate = useNavigate();
  const validation = useQuery({
    queryKey: ["run", validationId],
    queryFn: () => api<Run>(`/runs/${validationId}`),
    refetchInterval: (query) =>
      ["succeeded", "failed", "canceled", "interrupted"].includes(
        query.state.data?.status ?? "",
      )
        ? false
        : 3000,
  });
  const repair = useMutation({
    mutationFn: () =>
      api<Run>(`/coding/runs/${run.id}/repair`, { method: "POST" }),
    onSuccess: (result) =>
      onQueued ? onQueued(result) : navigate(`/runs/${result.id}`),
  });
  const next =
    run.metadata?.continuation_run_id ??
    run.metadata?.repair_run_id ??
    validation.data?.metadata?.repair_run_id;
  return (
    <div className="content-panel">
      <p>
        <Link className="text-link" to={`/runs/${validationId}`}>
          Validation:{" "}
          {validation.data?.status.replaceAll("_", " ") ?? "loading"} →
        </Link>
      </p>
      <ErrorNotice error={validation.error || repair.error} />
      {validation.data?.metadata?.repair_budget_exhausted === true && (
        <p className="notice">
          Automatic repair limit reached. Inspect the latest diff and failures
          before requesting another attempt.
        </p>
      )}
      {typeof next === "string" ? (
        <p>
          This attempt was superseded.{" "}
          <Link className="text-link" to={`/runs/${next}`}>
            {run.metadata?.continuation_run_id
              ? "Open latest work →"
              : "Open repair →"}
          </Link>
        </p>
      ) : run.executor_type === "local_proposal" &&
        run.status === "succeeded" &&
        !run.metadata?.commit_run_id &&
        validation.data?.status === "failed" &&
        validation.data.error_type === "ValidationFailed" ? (
        <>
          <p className="muted">
            Let the same local model fix the failing checks in this task
            worktree. It receives the saved validation results and original file
            scope. Tests run again; you review the updated diff before
            committing.
          </p>
          <Button disabled={repair.isPending} onClick={() => repair.mutate()}>
            {repair.isPending ? "Queuing repair…" : "Repair with Local AI"}
          </Button>
        </>
      ) : null}
      {!next &&
        validation.data?.status === "succeeded" &&
        run.status === "succeeded" &&
        !!(run.metadata?.coding_review as Review)?.files.length && (
          <CommitReview run={run} onQueued={onQueued} />
        )}
    </div>
  );
}
