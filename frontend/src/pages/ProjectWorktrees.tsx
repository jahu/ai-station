import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { GitBranch } from "lucide-react";
import { api, type Run } from "../api";
import { Badge, Empty, ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";
import { terminal } from "../lib/utils";

interface Worktree {
  id: string;
  run_id: string;
  run_status: string;
  relative_path: string;
  branch: string;
  base_branch: string;
  owned: boolean;
}

export default function ProjectWorktrees({
  project,
}: {
  project: { id: string; updated_at: string; integration_branch: string };
}) {
  const navigate = useNavigate();
  const worktrees = useQuery({
    queryKey: ["project-worktrees", project.id],
    queryFn: () => api<Worktree[]>(`/projects/${project.id}/worktrees`),
    refetchInterval: 5000,
  });
  const prepare = useMutation({
    mutationFn: () =>
      api<Run>(`/projects/${project.id}/worktrees`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_updated_at: project.updated_at }),
      }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });
  const validate = useMutation({
    mutationFn: (worktreeId: string) =>
      api<Run>(`/projects/${project.id}/worktrees/${worktreeId}/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_updated_at: project.updated_at }),
      }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });
  const active = worktrees.data?.some(
    (worktree) => !terminal.has(worktree.run_status),
  );
  return (
    <section className="panel content-panel mt">
      <div className="row spread project-worktrees-heading">
        <h2 className="row">
          <GitBranch size={17} />
          Isolated worktrees
        </h2>
        <Button
          disabled={
            prepare.isPending ||
            active ||
            worktrees.isPending ||
            worktrees.isError
          }
          onClick={() => prepare.mutate()}
        >
          {prepare.isPending ? "Queueing…" : "Prepare isolated worktree"}
        </Button>
      </div>
      <p className="muted">
        Creates a new task branch from the local{" "}
        <strong>{project.integration_branch}</strong> branch in application
        storage. This starts a local Run with Git and workspace write
        permissions. Your active checkout stays in place; no coding agent or
        validation command is launched.
      </p>
      <p className="muted">
        Run saved validation executes the project's saved test, lint and build
        commands in a prepared worktree. Network access is blocked; dependencies
        must already be available there. Logs and the result report appear in
        the validation Run.
      </p>
      <ErrorNotice error={worktrees.error ?? prepare.error ?? validate.error} />
      {worktrees.isPending ? (
        <Loading />
      ) : worktrees.data?.length ? (
        <div className="worktree-list">
          {worktrees.data.map((worktree) => (
            <article key={worktree.id}>
              <div className="row spread">
                <Link className="text-link" to={`/runs/${worktree.run_id}`}>
                  Inspect preparation Run →
                </Link>
                <Badge status={worktree.run_status} />
              </div>
              {worktree.owned && worktree.run_status === "succeeded" && (
                <Button
                  variant="secondary"
                  disabled={validate.isPending || active}
                  onClick={() => validate.mutate(worktree.id)}
                >
                  {validate.isPending ? "Queueing…" : "Run saved validation"}
                </Button>
              )}
              <p className="mono">{worktree.branch}</p>
              <p className="mono muted">{worktree.relative_path}</p>
              <p className="muted">
                {worktree.owned
                  ? "Prepared and recorded. Preserved for review."
                  : terminal.has(worktree.run_status)
                    ? "Preparation was not confirmed. Inspect the Run and any partial data before continuing."
                    : "Preparation has not completed yet."}
              </p>
            </article>
          ))}
        </div>
      ) : (
        <Empty title="No worktrees prepared">
          Prepare a separate checkout for an upcoming coding task. Worktrees and
          branches are preserved; automatic cleanup is disabled.
        </Empty>
      )}
    </section>
  );
}
