import { Link, useNavigate } from "react-router-dom";
import { useId, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, GitCommitHorizontal, Check } from "lucide-react";
import { api, type Artifact, type Run } from "../api";
import { Button } from "../components/ui/button";
import { ErrorNotice } from "../components/common";
import Markdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import { useListKeyboard } from "./useListKeyboard";
import { ReviewChoiceList } from "./ReviewChoiceList";

type Review = {
  exploration?: {
    request: Record<string, unknown>;
    result: Record<string, unknown>;
  }[];
  branch: string;
  base_commit?: string;
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
    <section className="panel content-panel" aria-label="Coding review">
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
          <ReviewSummary run={run} review={review} />
          <ReviewArtifacts runId={run.id} />
          {!!review.exploration?.length && (
            <ExplorationSteps steps={review.exploration} />
          )}
          <ReviewFiles files={review.files} />
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

function ReviewSummary({ run, review }: { run: Run; review: Review }) {
  const insertions = review.files.reduce((n, file) => n + file.insertions, 0);
  const deletions = review.files.reduce((n, file) => n + file.deletions, 0);
  const cumulative =
    run.parameters?.cumulative === true ||
    typeof run.metadata?.repair_source_run_id === "string";
  const base =
    typeof review.base_commit === "string" && review.base_commit
      ? review.base_commit.slice(0, 12)
      : "";
  return (
    <p className="coding-review-summary">
      {review.files.length} {review.files.length === 1 ? "file" : "files"} · +
      {insertions} / −{deletions}
      {cumulative
        ? " · cumulative against the task base"
        : " · this proposal only"}
      {base ? ` · base ${base}` : ""}
    </p>
  );
}

function ReviewArtifacts({ runId }: { runId: string }) {
  const artifacts = useQuery({
    queryKey: ["run-artifacts", runId],
    queryFn: () => api<Artifact[]>(`/artifacts?run_id=${runId}`),
  });
  const items = Array.isArray(artifacts.data) ? artifacts.data : [];
  const patch = items.find((item) => item.type === "git_diff");
  const report = items.find(
    (item) =>
      item.type === "json" && item.original_filename === "coding-review.json",
  );
  if (!patch && !report) return null;
  return (
    <div
      className="coding-review-artifacts"
      role="group"
      aria-label="Review artifacts"
    >
      {patch && (
        <>
          <a
            className="text-link"
            href={`/api/artifacts/${patch.id}/file`}
            download={patch.original_filename || "changes.diff"}
          >
            <Download size={14} />
            Download patch
          </a>
          <Link className="text-link" to={`/library/${patch.id}`}>
            Open patch in Library →
          </Link>
        </>
      )}
      {report && (
        <a
          className="text-link"
          href={`/api/artifacts/${report.id}/file`}
          download={report.original_filename || "coding-review.json"}
        >
          <Download size={14} />
          Download review JSON
        </a>
      )}
    </div>
  );
}

function ExplorationSteps({
  steps,
}: {
  steps: NonNullable<Review["exploration"]>;
}) {
  const headingId = useId();
  const labelId = useId();
  const items = steps.map((step, i) => ({
    key: `${i}-${String(step.request.tool)}`,
    index: i,
    tool: String(step.request.tool),
    step,
  }));
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.key,
  );
  return (
    <details>
      <summary id={headingId}>
        Repository exploration · {steps.length} steps
      </summary>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a step while the list is focused. There is no
        inspectable exploration Run; observations stay on this review.
      </p>
      <div
        ref={listRef}
        className="coding-exploration"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {items.map((item, i) => (
          <article
            key={item.key}
            aria-label={`Step ${item.index + 1} ${item.tool}`}
            {...itemProps(i, item.key)}
          >
            <strong>
              {item.index + 1}. {item.tool}
            </strong>
            <pre>{JSON.stringify(item.step.request, null, 2)}</pre>
            <details>
              <summary>Observed result</summary>
              <pre>{JSON.stringify(item.step.result, null, 2)}</pre>
            </details>
          </article>
        ))}
      </div>
    </details>
  );
}

function ReviewFiles({ files }: { files: Review["files"] }) {
  const labelId = useId();
  const { listRef, index, setSelectedKey, onKeyDown, itemProps } =
    useListKeyboard(files, (item) => item.path);
  if (!files.length) return <p>No file contents changed.</p>;
  const file = files[index] ?? files[0];
  return (
    <div className="coding-review-files">
      <p id={labelId} className="muted">
        Arrow keys choose a file while the list is focused. Only the selected
        patch is shown. Enter does not open a Run.
      </p>
      <div
        ref={listRef}
        role="listbox"
        aria-labelledby={labelId}
        aria-activedescendant={file ? `${labelId}-${index}` : undefined}
        className="coding-review-file-list"
        onKeyDown={onKeyDown}
      >
        {files.map((item, i) => (
          <div
            id={`${labelId}-${i}`}
            key={item.path}
            role="option"
            aria-selected={i === index}
            aria-label={`File ${item.path}`}
            className="coding-review-file"
            onClick={() => setSelectedKey(item.path)}
            {...itemProps(i, item.path)}
          >
            <span className="mono">{item.path}</span>
            <span>
              +{item.insertions} / −{item.deletions}
            </span>
          </div>
        ))}
      </div>
      <div
        className="coding-review-diff markdown"
        aria-label={`Diff for ${file.path}`}
      >
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
    </div>
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
      <ReviewChoiceList
        checked={reviewed}
        disabled={commit.isPending}
        onChange={setReviewed}
      >
        I reviewed the diff and validation results.
      </ReviewChoiceList>
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
