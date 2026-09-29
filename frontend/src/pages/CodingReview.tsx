import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { GitCommitHorizontal, Check } from "lucide-react";
import { api } from "../api";
import { Button } from "../components/ui/button";
import { ErrorNotice } from "../components/common";
import Markdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import type { Run } from "../api";

type Review = {
  branch: string;
  files: {
    path: string;
    diff: string;
    insertions: number;
    deletions: number;
  }[];
};

export default function CodingReview({ run }: { run: Run }) {
  const local = run.metadata?.execution_location === "local";
  const next = run.metadata?.coding_run_id;
  const validation = run.metadata?.validation_run_id;
  const review = run.metadata?.coding_review as Review | undefined;
  if (!next && !review && run.metadata?.execution_location !== "external")
    return null;
  return (
    <section className="panel content-panel">
      <span className="chip">{local ? "LOCAL AI" : "EXTERNAL CURSOR AI"}</span>
      {typeof next === "string" && (
        <p>
          <Link className="text-link" to={`/runs/${next}`}>
            Open {local ? "local coding" : "Cursor"} execution →
          </Link>
        </p>
      )}
      {review && (
        <>
          <h2 className="mt">
            {run.metadata?.review_status === "committed"
              ? "Reviewed changes committed"
              : "Changes awaiting review"}
          </h2>
          <p className="mono">{review.branch}</p>
          <p>
            Agent completion is not a correctness verdict. Review the changes
            and validation before integrating this branch.
          </p>
          {typeof validation === "string" ? (
            <p>
              <Link className="text-link" to={`/runs/${validation}`}>
                Inspect validation results →
              </Link>
            </p>
          ) : (
            <p className="notice">
              No validation commands were configured. This proposal has not been
              tested.
            </p>
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
          {review.files.length > 0 && run.status === "succeeded" && (
            <CommitReview run={run} />
          )}
        </>
      )}
    </section>
  );
}

function CommitReview({ run }: { run: Run }) {
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
    onSuccess: (result) => navigate(`/runs/${result.id}`),
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
