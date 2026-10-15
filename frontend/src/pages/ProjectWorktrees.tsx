import { useId, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { GitBranch } from "lucide-react";
import { api, type Run } from "../api";
import { Badge, Empty, ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";
import { terminal } from "../lib/utils";
import { useListKeyboard } from "./useListKeyboard";

interface Worktree {
  id: string;
  run_id: string;
  run_status: string;
  relative_path: string;
  branch: string;
  base_branch: string;
  owned: boolean;
  removed_at: string | null;
  expires_at: string | null;
}

function WorktreeCards({
  worktrees,
  projectId,
  busy,
  confirmId,
  setConfirmId,
  dependenciesPending,
  validatePending,
  keepPending,
  removePending,
  onDependencies,
  onValidate,
  onKeep,
  onRemove,
}: {
  worktrees: Worktree[];
  projectId: string;
  busy: boolean;
  confirmId: string | null;
  setConfirmId: (id: string | null) => void;
  dependenciesPending: boolean;
  validatePending: boolean;
  keepPending: boolean;
  removePending: boolean;
  onDependencies: (id: string) => void;
  onValidate: (id: string) => void;
  onKeep: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  const headingId = useId();
  const labelId = useId();
  const navigate = useNavigate();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    worktrees,
    (worktree) => worktree.id,
  );
  const selected = worktrees[index];
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key !== "Enter" || event.defaultPrevented) return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input")) return;
    if (selected?.run_id) {
      event.preventDefault();
      navigate(`/runs/${selected.run_id}`);
    }
  };
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="sr-only">
        Prepared worktrees
      </h3>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a worktree while the list is focused. Enter inspects
        its preparation Run. View tagged Runs stays on the selected row.
        Install, validate, keep and remove stay on the selected row. Those links
        do not Enable or Run now or start a coding Run.
      </p>
      <div
        ref={listRef}
        className="worktree-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {worktrees.map((worktree, i) => {
          const current = i === index;
          const shortId = worktree.id.slice(0, 8);
          const action = (verb: string) =>
            `${verb} ${worktree.branch} ${shortId}`;
          return (
            <article key={worktree.id} {...itemProps(i, worktree.id)}>
              <div className="row spread">
                <Link
                  className="text-link"
                  to={`/runs/${worktree.run_id}`}
                  tabIndex={current ? 0 : -1}
                  aria-label={action("Inspect")}
                >
                  Inspect preparation Run →
                </Link>
                <Badge
                  status={worktree.removed_at ? "removed" : worktree.run_status}
                />
              </div>
              <Link
                className="text-link"
                to={`/runs?project_id=${projectId}`}
                tabIndex={current ? 0 : -1}
                aria-label={`View tagged Runs ${shortId}`}
              >
                View tagged Runs
              </Link>
              {worktree.owned &&
                worktree.run_status === "succeeded" &&
                !worktree.removed_at && (
                  <>
                    <Button
                      variant="secondary"
                      tabIndex={current ? 0 : -1}
                      disabled={busy}
                      aria-label={action("Install project dependencies")}
                      onClick={() => onDependencies(worktree.id)}
                    >
                      {dependenciesPending
                        ? "Queueing…"
                        : "Install project dependencies"}
                    </Button>
                    <Button
                      variant="secondary"
                      tabIndex={current ? 0 : -1}
                      disabled={busy}
                      aria-label={action("Run saved validation")}
                      onClick={() => onValidate(worktree.id)}
                    >
                      {validatePending ? "Queueing…" : "Run saved validation"}
                    </Button>
                    {worktree.expires_at && (
                      <Button
                        variant="secondary"
                        tabIndex={current ? 0 : -1}
                        disabled={busy}
                        aria-label={action("Don't auto-remove")}
                        onClick={() => onKeep(worktree.id)}
                      >
                        {keepPending ? "Saving…" : "Don't auto-remove"}
                      </Button>
                    )}
                  </>
                )}
              {!worktree.removed_at &&
                (confirmId === worktree.id ? (
                  <div className="row">
                    <p role="alert">
                      Uncommitted files and unmerged commits will be lost.
                    </p>
                    <Button
                      tabIndex={current ? 0 : -1}
                      disabled={busy}
                      aria-label={action("Permanently remove worktree")}
                      onClick={() => onRemove(worktree.id)}
                    >
                      {removePending
                        ? "Queueing…"
                        : "Permanently remove worktree"}
                    </Button>
                    <Button
                      variant="secondary"
                      tabIndex={current ? 0 : -1}
                      aria-label={action("Keep worktree")}
                      onClick={() => setConfirmId(null)}
                    >
                      Keep worktree
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="secondary"
                    tabIndex={current ? 0 : -1}
                    disabled={busy}
                    aria-label={action("Remove worktree")}
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
                    ? worktree.expires_at
                      ? "Prepared and recorded. Legacy expiry is disabled; kept until you remove it."
                      : "Prepared and recorded. Kept until you remove it."
                    : terminal.has(worktree.run_status)
                      ? "Preparation was not confirmed. Inspect the Run and any partial data before removing."
                      : "Preparation has not completed yet."}
              </p>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export default function ProjectWorktrees({
  project,
}: {
  project: { id: string; updated_at: string; integration_branch: string };
}) {
  const navigate = useNavigate();
  const cache = useQueryClient();
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
  const keep = useMutation({
    mutationFn: (worktreeId: string) =>
      api<Worktree>(`/projects/${project.id}/worktrees/${worktreeId}/keep`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_updated_at: project.updated_at }),
      }),
    onSuccess: () =>
      cache.invalidateQueries({ queryKey: ["project-worktrees", project.id] }),
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
    keep.isPending ||
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
        <code>pyproject.toml</code> project.dependencies, or the manifest
        selected in Validation environment. A configured frontend folder is
        prepared in its own dependency Run. A local <code>vendor/</code>{" "}
        directory of wheels is used offline; otherwise the Run may download
        wheels from PyPI. Only binary wheels are installed. URLs, VCS refs and
        extra indexes are rejected. Git metadata stays read-only. For Node
        projects, a missing package-lock.json is created offline from verified
        public npm metadata before installation. Existing lockfiles are checked.
        Install scripts stay disabled; a configured Node/npm runtime is
        required.
      </p>
      <p className="muted">
        Run saved validation executes the project's saved test, lint and build
        commands in a prepared worktree. Network access is blocked; packages
        must already be in the worktree environment or system runtime paths.
        Logs and the result report appear in the validation Run.
      </p>
      <p className="muted">
        Worktrees are kept until you explicitly remove them. Inactivity never
        deletes your code, uncommitted changes or task branch.
      </p>
      <p className="muted">
        Remove permanently discards this checkout, including uncommitted files
        and unmerged commits on its local task branch. It does not change your
        current repository, push, or delete GitHub branches. Coding
        conversations that used the worktree cannot continue.
      </p>
      <ErrorNotice
        error={
          worktrees.error ??
          prepare.error ??
          dependencies.error ??
          validate.error ??
          keep.error ??
          remove.error
        }
      />
      {worktrees.isPending ? (
        <Loading />
      ) : worktrees.data?.length ? (
        <WorktreeCards
          worktrees={worktrees.data}
          projectId={project.id}
          busy={busy}
          confirmId={confirmId}
          setConfirmId={setConfirmId}
          dependenciesPending={dependencies.isPending}
          validatePending={validate.isPending}
          keepPending={keep.isPending}
          removePending={remove.isPending}
          onDependencies={(id) => dependencies.mutate(id)}
          onValidate={(id) => validate.mutate(id)}
          onKeep={(id) => keep.mutate(id)}
          onRemove={(id) => remove.mutate(id)}
        />
      ) : (
        <Empty title="No worktrees prepared">
          Prepare a separate checkout for an upcoming coding task. Unused owned
          worktrees are removed after seven days unless you keep them.
        </Empty>
      )}
    </section>
  );
}
