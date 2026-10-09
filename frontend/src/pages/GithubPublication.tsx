import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { GitPullRequest, Upload } from "lucide-react";
import { api, type Run } from "../api";
import { Button } from "../components/ui/button";
import { ErrorNotice, Loading } from "../components/common";

type Preview = {
  repository: string;
  branch: string;
  commit: string;
  base: string;
  expected_updated_at: string;
  project_id: string;
  github_cli_available: boolean;
  blocked_reason: string | null;
  publication_run_id: string | null;
};
type Result = { pr_url?: string; stage?: string; outcome?: string };

export default function GithubPublication({ run }: { run: Run }) {
  if (run.executor_type === "reviewed_commit" && run.status === "succeeded")
    return <PublishCommit run={run} />;
  if (
    run.executor_type !== "github_publication" &&
    run.executor_type !== "publication_reconcile"
  )
    return null;
  const result = (run.metadata?.publication ??
    run.metadata?.publication_progress) as Result | undefined;
  const repository = String(run.parameters.repository);
  return (
    <section className="panel content-panel">
      <h2 className="row">
        <GitPullRequest size={20} /> GitHub publication
      </h2>
      <p>
        <strong>{repository}</strong> · {String(run.parameters.branch)} →{" "}
        {String(run.parameters.base)}
      </p>
      <p className="mono">Commit {String(run.parameters.commit)}</p>
      {result?.stage && (
        <p>Last recorded step: {result.stage.replaceAll("_", " ")}</p>
      )}
      {result?.pr_url ? (
        <a
          className="text-link"
          href={result.pr_url}
          target="_blank"
          rel="noreferrer"
        >
          Open draft pull request ↗
        </a>
      ) : run.executor_type === "github_publication" &&
        ["failed", "interrupted", "canceled"].includes(run.status) ? (
        <UncertainPublication run={run} repository={repository} />
      ) : result?.outcome === "not_on_github" ? (
        <p className="notice">
          GitHub does not have this task branch. Publication was not retried and
          nothing was pushed.
        </p>
      ) : (
        <p className="muted">
          Publishing the approved task commit and opening a draft PR. This does
          not merge or deploy changes.
        </p>
      )}
    </section>
  );
}

function UncertainPublication({
  run,
  repository,
}: {
  run: Run;
  repository: string;
}) {
  const navigate = useNavigate();
  const reconcile = useMutation({
    mutationFn: () =>
      api<Run>(`/coding/runs/${run.id}/reconcile`, { method: "POST" }),
    onSuccess: (result) => navigate(`/runs/${result.id}`),
  });
  const next = run.metadata?.reconcile_run_id;
  return (
    <>
      <p className="notice">
        Publication stopped. GitHub may already have the branch or PR. This
        action inspects GitHub and can open the approved draft PR. It never
        pushes again.{" "}
        <a
          className="text-link"
          href={`https://github.com/${repository}`}
          target="_blank"
          rel="noreferrer"
        >
          Inspect the repository ↗
        </a>
      </p>
      {typeof next === "string" ? (
        <Link className="text-link" to={`/runs/${next}`}>
          Inspect reconciliation →
        </Link>
      ) : (
        <>
          <ErrorNotice error={reconcile.error} />
          <Button
            disabled={reconcile.isPending}
            onClick={() => reconcile.mutate()}
          >
            {reconcile.isPending ? "Queueing…" : "Reconcile with GitHub"}
          </Button>
        </>
      )}
    </>
  );
}

function PublishCommit({ run }: { run: Run }) {
  const navigate = useNavigate();
  const [title, setTitle] = useState("Review AI Station changes");
  const [body, setBody] = useState("");
  const [approval, setApproval] = useState<string | null>(null);
  const preview = useQuery({
    queryKey: ["publication-preview", run.id],
    queryFn: () => api<Preview>(`/coding/runs/${run.id}/publication`),
    retry: false,
  });
  const scope = JSON.stringify({ target: preview.data, title, body });
  const approved = approval === scope;
  const publish = useMutation({
    mutationFn: () =>
      api<Run>(`/coding/runs/${run.id}/publication`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approved: true,
          repository: preview.data!.repository,
          commit: preview.data!.commit,
          base: preview.data!.base,
          expected_updated_at: preview.data!.expected_updated_at,
          title,
          body,
        }),
      }),
    onSuccess: (result) => navigate(`/runs/${result.id}`),
  });
  const next =
    run.metadata?.publication_run_id ?? preview.data?.publication_run_id;
  return (
    <section className="panel content-panel">
      <h2 className="row">
        <GitPullRequest size={20} /> Publish reviewed changes
      </h2>
      {typeof next === "string" ? (
        <Link className="text-link" to={`/runs/${next}`}>
          Inspect publication →
        </Link>
      ) : (
        <>
          <ErrorNotice error={preview.error ?? publish.error} />
          {preview.isPending && <Loading />}
          {preview.data && (
            <>
              <p>
                <strong>{preview.data.repository}</strong>
              </p>
              <p className="mono">
                {preview.data.branch} → {preview.data.base}
                <br />
                {preview.data.commit}
              </p>
              {preview.data.blocked_reason ? (
                <p className="notice">
                  {preview.data.blocked_reason}{" "}
                  <Link
                    className="text-link"
                    to={`/projects/${preview.data.project_id}`}
                  >
                    Project settings →
                  </Link>
                </p>
              ) : !preview.data.github_cli_available ? (
                <p className="notice">
                  GitHub CLI is unavailable on the Host Runner.
                </p>
              ) : (
                <form
                  className="image-form project-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (approved) publish.mutate();
                  }}
                >
                  <fieldset disabled={publish.isPending}>
                    <label>
                      PR title
                      <input
                        required
                        maxLength={200}
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                      />
                    </label>
                    <label>
                      PR description
                      <textarea
                        rows={5}
                        maxLength={20000}
                        value={body}
                        onChange={(event) => setBody(event.target.value)}
                        placeholder="What changed and how was it validated?"
                      />
                    </label>
                    <label className="project-checkbox">
                      <input
                        type="checkbox"
                        checked={approved}
                        onChange={(event) =>
                          setApproval(event.target.checked ? scope : null)
                        }
                      />
                      I approve publishing this commit and PR text to the GitHub
                      repository shown above.
                    </label>
                    <Button
                      disabled={!approved || !title.trim() || publish.isPending}
                    >
                      <Upload size={16} />
                      {publish.isPending
                        ? "Queuing publication…"
                        : "Publish branch and create draft PR"}
                    </Button>
                  </fieldset>
                  <p className="muted">
                    Uses the Host Runner’s existing GitHub login. The task must
                    start from the current remote integration head. No force
                    push, merge or deployment.
                  </p>
                </form>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
