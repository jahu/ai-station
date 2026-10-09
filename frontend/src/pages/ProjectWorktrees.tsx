import { useState } from "react";
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
  removed_at: string | null;
}

export default function ProjectWorktrees({
  project,
}: {
  project: { id: string; updated_at: string; integration_branch: string };
}) {
  const navigate = useNavigate();
  const [confirmId, setConfirmId] = useState<string | null>(null);
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
  const dependencies = useMutation({
    mutationFn: (worktreeId: string) =>
      api<Run>(`/projects/${project.id}/worktrees/${worktreeId}/dependencies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_updated_at: project.updated_at }),
      }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });
  const remove = useMutation({
    mutationFn: (worktreeId: string) =>
      api<Run>(`/projects/${project.id}/worktrees/${worktreeId}/remove`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_updated_at: project.updated_at }),
      }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });
  const active = worktrees.data?.some(
    (worktree) => !terminal.has(worktree.run_status),
  );
  const busy =
    prepare.isPending ||
    validate.isPending ||
    dependencies.isPending ||
    remove.isPending ||
    active ||
    worktrees.isPending ||
    worktrees.isError;
  return (
    <section className="panel content-panel mt">
      <div className="row spread project-worktrees-heading">
        <h2 className="row">
          <GitBranch size={17} />
          Isolated worktrees
        </h2>
        <Button disabled={busy} onClick={() => prepare.mutate()}>
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
        Install project dependencies creates or reuses the worktree Python
        environment and installs from <code>requirements.txt</code> or{" "}
        <code>pyproject.toml</code> project.dependencies. A local{" "}
        <code>vendor/</code> directory of wheels is used offline; otherwise the
        Run may download wheels from PyPI. Only binary wheels are installed.
        URLs, VCS refs and extra indexes are rejected. Git metadata stays
        read-only.
      </p>
      <p className="muted">
        Run saved validation executes the project's saved test, lint and build
        commands in a prepared worktree. Network access is blocked; packages
        must already be in the worktree environment or system runtime paths.
        Logs and the result report appear in the validation Run.
      </p>
      <p className="muted">
        Remove deletes only this owned checkout and its local task branch. It
        does not change your current repository, push, or delete GitHub
        branches. Coding conversations that used the worktree cannot continue.
      </p>
      <ErrorNotice
        error={
          worktrees.error ??
          prepare.error ??
          dependencies.error ??
          validate.error ??
          remove.error
        }
      />
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
                <Badge
                  status={worktree.removed_at ? "removed" : worktree.run_status}
                />
              </div>
              {worktree.owned &&
                worktree.run_status === "succeeded" &&
                !worktree.removed_at && (
                  <>
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => dependencies.mutate(worktree.id)}
                    >
                      {dependencies.isPending
                        ? "Queueing…"
                        : "Install project dependencies"}
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={busy}
                      onClick={() => validate.mutate(worktree.id)}
                    >
                      {validate.isPending ? "Queueing…" : "Run saved validation"}
                    </Button>
                  </>
                )}
              {!worktree.removed_at &&
                (confirmId === worktree.id ? (
                  <div className="row">
                    <Button
                      disabled={busy}
                      onClick={() => remove.mutate(worktree.id)}
                    >
                      {remove.isPending
                        ? "Queueing…"
                        : "Permanently remove worktree"}
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => setConfirmId(null)}
                    >
                      Keep worktree
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() => setConfirmId(worktree.id)}
                  >
                    Remove worktree…
                  </Button>
                ))}
              <p className="mono">{worktree.branch}</p>
              <p className="mono muted">{worktree.relative_path}</p>
              <p className="muted">
                {worktree.removed_at
                  ? "Removed. The local task branch and owned checkout are gone; GitHub remotes were not changed."
                  : worktree.owned
                    ? "Prepared and recorded. Preserved until you remove it."
                    : terminal.has(worktree.run_status)
                      ? "Preparation was not confirmed. Inspect the Run and any partial data before removing."
                      : "Preparation has not completed yet."}
              </p>
            </article>
          ))}
        </div>
      ) : (
        <Empty title="No worktrees prepared">
          Prepare a separate checkout for an upcoming coding task. Owned
          worktrees stay until you remove them; automatic cleanup is disabled.
        </Empty>
      )}
    </section>
  );
}
