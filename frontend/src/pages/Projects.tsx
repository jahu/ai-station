import { useEffect, useId, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  ArrowLeft,
  FolderGit2,
  GitBranch,
  Plus,
  RefreshCw,
} from "lucide-react";
import { api, type Run } from "../api";
import { Empty, ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import ProjectAgents from "./ProjectAgents";
import ProjectCodingSessions from "./ProjectCodingSessions";
import ProjectWorktrees from "./ProjectWorktrees";
import { terminal } from "../lib/utils";
import { useListKeyboard } from "./useListKeyboard";

interface Project {
  id: string;
  name: string;
  repo_path: string;
  default_branch: string;
  integration_branch: string;
  protected_branches: string[];
  preferred_executor: string;
  test_commands: string[][];
  lint_commands: string[][];
  build_commands: string[][];
  agent_rules: string;
  pr_policy: Record<string, boolean>;
  updated_at: string;
}
interface RepoStatus {
  branch: string;
  dirty: boolean;
  porcelain: string;
  repo_path: string;
  checked_at: string;
}

const policyDefaults = {
  commit_task_branch: true,
  push_task_branch: false,
  pr_to_integration: false,
  pr_to_production: false,
  automatic_merge: false,
  force_push: false,
};
const commandText = (commands: string[][]) =>
  commands.map((command) => JSON.stringify(command)).join("\n");
type GitPolicy = typeof policyDefaults;
const gitPolicyItems = [
  {
    key: "commit_task_branch" as const,
    title: "Allow commits on task branches",
  },
  {
    key: "push_task_branch" as const,
    title: "Allow pushing task branches",
  },
  {
    key: "pr_to_integration" as const,
    title: "Allow PRs to the integration branch",
  },
];
function parseCommands(text: string): string[][] {
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      let command: unknown;
      try {
        command = JSON.parse(line);
      } catch {
        throw new Error(
          'Each command must be a JSON argument array, such as ["pytest", "-q"].',
        );
      }
      if (
        !Array.isArray(command) ||
        !command.length ||
        !command.every((argument) => typeof argument === "string")
      ) {
        throw new Error(
          "Each command must be a nonempty array of string arguments.",
        );
      }
      return command;
    });
}

function PolicyChoiceList({
  policy,
  onChange,
}: {
  policy: GitPolicy;
  onChange: (policy: GitPolicy) => void;
}) {
  const labelId = useId();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    gitPolicyItems,
    (item) => item.key,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    const item = gitPolicyItems[index];
    if (!item) return;
    event.preventDefault();
    onChange({ ...policy, [item.key]: !policy[item.key] });
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a Git policy while the list is focused. Space or Enter
        selects it. Saving still does not commit, push, or open a PR. There is
        no inspectable policy Run.
      </p>
      <div
        ref={listRef}
        className="policy-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {gitPolicyItems.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Policy ${item.key}`}
              {...itemProps(i, item.key)}
            >
              <label className="project-checkbox">
                <input
                  type="checkbox"
                  checked={policy[item.key]}
                  tabIndex={current ? 0 : -1}
                  onChange={(event) =>
                    onChange({ ...policy, [item.key]: event.target.checked })
                  }
                />
                {item.title}
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}

function ProjectForm({
  project,
  onSaved,
}: {
  project?: Project;
  onSaved: (project: Project) => void;
}) {
  const [name, setName] = useState(project?.name ?? "");
  const [path, setPath] = useState("");
  const [defaultBranch, setDefaultBranch] = useState(
    project?.default_branch ?? "main",
  );
  const [integrationBranch, setIntegrationBranch] = useState(
    project?.integration_branch ?? "develop",
  );
  const [protectedBranches, setProtectedBranches] = useState(
    project?.protected_branches.join(", ") ?? "main, master",
  );
  const [executor, setExecutor] = useState(
    project?.preferred_executor ?? "codex",
  );
  const [tests, setTests] = useState(commandText(project?.test_commands ?? []));
  const [lint, setLint] = useState(commandText(project?.lint_commands ?? []));
  const [build, setBuild] = useState(
    commandText(project?.build_commands ?? []),
  );
  const [rules, setRules] = useState(project?.agent_rules ?? "");
  const [policy, setPolicy] = useState({
    ...policyDefaults,
    ...project?.pr_policy,
  });
  const save = useMutation({
    mutationFn: () =>
      api<Project>(project ? `/projects/${project.id}` : "/projects", {
        method: project ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          default_branch: defaultBranch,
          integration_branch: integrationBranch,
          protected_branches: protectedBranches
            .split(",")
            .map((branch) => branch.trim())
            .filter(Boolean),
          preferred_executor: executor,
          test_commands: parseCommands(tests),
          lint_commands: parseCommands(lint),
          build_commands: parseCommands(build),
          agent_rules: rules,
          pr_policy: policy,
          ...(project
            ? { expected_updated_at: project.updated_at }
            : { repo_path: path }),
        }),
      }),
    onSuccess: onSaved,
  });
  return (
    <form
      className="image-form project-form"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <ErrorNotice error={save.error} />
      <fieldset disabled={save.isPending}>
        <label>
          Project name
          <input
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="AI Station"
          />
        </label>
        {!project && (
          <label>
            Repository path on host
            <input
              required
              maxLength={4096}
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="/path/to/repository"
            />
            <small className="muted">
              The Host Runner must allow this path and its Git metadata.
            </small>
          </label>
        )}
        <details>
          <summary>Advanced repository settings</summary>
          <div className="project-form-section">
            <div className="field-pair">
              <label>
                Default branch
                <input
                  required
                  maxLength={200}
                  value={defaultBranch}
                  onChange={(e) => setDefaultBranch(e.target.value)}
                />
              </label>
              <label>
                Integration branch
                <input
                  required
                  maxLength={200}
                  value={integrationBranch}
                  onChange={(e) => setIntegrationBranch(e.target.value)}
                />
              </label>
            </div>
            <label>
              Protected branches
              <input
                value={protectedBranches}
                onChange={(e) => setProtectedBranches(e.target.value)}
              />
              <small className="muted">
                Comma separated. The default branch, main, and master are always
                protected.
              </small>
            </label>
            <label>
              Preferred coding executor
              <select
                value={executor}
                onChange={(e) => setExecutor(e.target.value)}
              >
                <option value="codex">Codex</option>
                <option value="cursor">Cursor</option>
                <option value="claude" disabled>
                  Claude Code (unavailable)
                </option>
                <option value="local">Local model (experimental)</option>
              </select>
              <small className="muted">
                Used when you select Auto in Coding.
              </small>
            </label>
          </div>
        </details>
        <details>
          <summary>Validation commands and agent guidance</summary>
          <div className="project-form-section">
            <p className="muted">
              These trusted commands can run in a prepared worktree. Saving does
              not execute them. Use one JSON argument array per line.
            </p>
            <label>
              Test commands
              <textarea
                rows={3}
                value={tests}
                onChange={(e) => setTests(e.target.value)}
                placeholder={'["pytest", "-q"]'}
              />
            </label>
            <label>
              Lint commands
              <textarea
                rows={2}
                value={lint}
                onChange={(e) => setLint(e.target.value)}
                placeholder={'["ruff", "check", "."]'}
              />
            </label>
            <label>
              Build commands
              <textarea
                rows={2}
                value={build}
                onChange={(e) => setBuild(e.target.value)}
                placeholder={'["npm", "run", "build"]'}
              />
            </label>
            <label>
              Agent rules
              <textarea
                rows={4}
                maxLength={32000}
                value={rules}
                onChange={(e) => setRules(e.target.value)}
                placeholder="Project-specific instructions for future coding tasks"
              />
            </label>
          </div>
        </details>
        <details>
          <summary>Git workflow policy</summary>
          <div className="project-form-section">
            <p className="muted">
              Reviewed commits and GitHub publication follow these rules. Force
              push, production PRs, and automatic merge remain disabled.
            </p>
            <PolicyChoiceList
              policy={policy}
              onChange={(next) => setPolicy(next)}
            />
          </div>
        </details>
        <Button type="submit">
          {save.isPending
            ? "Saving…"
            : project
              ? "Save project settings"
              : "Validate and register"}
        </Button>
      </fieldset>
    </form>
  );
}

function ProjectCards({ projects }: { projects: Project[] }) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    projects,
    (project) => project.id,
  );
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="sr-only">
        Projects
      </h2>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a project while the list is focused. Enter inspects
        it.
      </p>
      <div
        ref={listRef}
        className="project-grid"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {projects.map((project, i) => (
          <Link
            className="panel project-card"
            key={project.id}
            to={`/projects/${project.id}`}
            aria-label={`Inspect ${project.name} ${project.id.slice(0, 8)}`}
            {...itemProps(i, project.id)}
          >
            <div className="row spread">
              <FolderGit2 size={23} aria-hidden="true" />
              <span className="chip">HOST REPOSITORY</span>
            </div>
            <h2>{project.name}</h2>
            <p className="mono muted">{project.repo_path}</p>
            <div className="project-card-footer">
              <span>
                <GitBranch size={13} aria-hidden="true" />
                {project.integration_branch}
              </span>
              <span>{project.preferred_executor} preferred</span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

export function Projects() {
  const [offset, setOffset] = useState(0);
  const projects = useQuery({
    queryKey: ["projects", offset],
    queryFn: () => api<Project[]>(`/projects?limit=50&offset=${offset}`),
  });
  return (
    <>
      <PageTitle
        eyebrow="WORKSPACE / GIT REPOSITORIES"
        title="Projects"
        action={
          <Button asChild>
            <Link to="/projects/new">
              <Plus size={15} />
              New project
            </Link>
          </Button>
        }
      >
        Your repositories, branch policies, and coding preferences in one place.
      </PageTitle>
      <ErrorNotice error={projects.error} />
      {projects.isPending ? (
        <Loading />
      ) : (
        projects.data &&
        (projects.data.length ? (
          <ProjectCards projects={projects.data} />
        ) : (
          <section className="panel">
            <Empty title="No projects on this page">
              Create a project by name or connect an existing repository.
            </Empty>
          </section>
        ))
      )}
      <div className="row mt">
        <Button
          variant="secondary"
          disabled={!offset}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Previous
        </Button>
        <span className="muted">Page {offset / 50 + 1}</span>
        <Button
          variant="secondary"
          disabled={projects.isPending || projects.data?.length !== 50}
          onClick={() => setOffset(offset + 50)}
        >
          Next
        </Button>
      </div>
    </>
  );
}

export function NewProject() {
  const navigate = useNavigate();
  const cache = useQueryClient();
  const [name, setName] = useState("");
  const [existing, setExisting] = useState(false);
  const [params, setParams] = useSearchParams();
  const runId = params.get("setup");
  const setup = useQuery({
    queryKey: ["project-setup", runId],
    queryFn: () => api<Run>(`/runs/${runId}`),
    enabled: !!runId,
    refetchInterval: 1000,
  });
  const create = useMutation({
    mutationFn: () =>
      api<Run>("/projects/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      }),
    onSuccess: (run) => setParams({ setup: run.id }),
  });
  useEffect(() => {
    if (setup.data?.status === "succeeded" && setup.data.project_id) {
      void cache.invalidateQueries({ queryKey: ["projects"] });
      void cache.invalidateQueries({ queryKey: ["coding-projects"] });
      navigate(`/coding?project=${setup.data.project_id}`);
    }
  }, [setup.data, cache, navigate]);
  return (
    <>
      <Link className="back-link" to="/projects">
        <ArrowLeft size={14} />
        Projects
      </Link>
      <PageTitle
        eyebrow="WORKSPACE / NEW PROJECT"
        title="Give your project a name"
      >
        We’ll take care of the workspace. You can start describing what to build
        next.
      </PageTitle>
      <div className="new-project-grid">
        <section className="panel content-panel">
          <div className="project-create-tabs">
            <button aria-pressed={!existing} onClick={() => setExisting(false)}>
              Create new
            </button>
            <button aria-pressed={existing} onClick={() => setExisting(true)}>
              Connect existing repository
            </button>
          </div>
          {existing ? (
            <ProjectForm
              onSaved={(project) => {
                void cache.invalidateQueries({ queryKey: ["projects"] });
                void cache.invalidateQueries({ queryKey: ["coding-projects"] });
                navigate(`/coding?project=${project.id}`);
              }}
            />
          ) : (
            <form
              className="project-quick-create"
              onSubmit={(e) => {
                e.preventDefault();
                create.mutate();
              }}
            >
              <label>
                Project name
                <input
                  required
                  maxLength={200}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="My next idea"
                  disabled={!!runId}
                />
              </label>
              <p className="muted">
                A private local folder, Git history and a Python environment —
                prepared automatically. No remote repository or downloads.
              </p>
              <ErrorNotice error={create.error ?? setup.error} />
              {setup.data?.error_message && (
                <p role="alert" className="notice">
                  {setup.data.error_message}
                </p>
              )}
              {runId ? (
                <div className="project-setup-progress">
                  {!terminal.has(setup.data?.status ?? "queued") && <Loading />}
                  <strong>
                    {setup.data?.status === "failed" ||
                    setup.data?.status === "canceled" ||
                    setup.data?.status === "interrupted"
                      ? "Setup needs attention"
                      : "Preparing your project…"}
                  </strong>
                  <Link className="text-link" to={`/runs/${runId}`}>
                    Setup details →
                  </Link>
                  {terminal.has(setup.data?.status ?? "queued") && (
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => setParams({})}
                    >
                      Create another project
                    </Button>
                  )}
                </div>
              ) : (
                <Button disabled={!name.trim() || create.isPending}>
                  <Plus size={16} />
                  {create.isPending ? "Creating…" : "Create project"}
                </Button>
              )}
            </form>
          )}
        </section>
        <aside className="project-onboarding">
          <FolderGit2 size={32} />
          <h2>From idea to first change</h2>
          <ol>
            <li>
              <strong>Name your project</strong>
              <span>AI Station sets up its home on this machine.</span>
            </li>
            <li>
              <strong>Choose your agent</strong>
              <span>Work locally or use Cursor or Codex.</span>
            </li>
            <li>
              <strong>Describe, review, continue</strong>
              <span>Return to the conversation whenever you want.</span>
            </li>
          </ol>
          <small className="muted">
            Branches, validation commands and project rules are available in
            project settings.
          </small>
        </aside>
      </div>
    </>
  );
}

export function ProjectDetail() {
  const { id } = useParams();
  const cache = useQueryClient();
  const [saved, setSaved] = useState(false);
  const project = useQuery({
    queryKey: ["project", id],
    queryFn: () => api<Project>(`/projects/${id}`),
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const status = useQuery({
    queryKey: ["project-status", id],
    queryFn: () => api<RepoStatus>(`/projects/${id}/status`),
    enabled: !!project.data,
    retry: false,
    refetchOnWindowFocus: false,
  });
  return (
    <>
      <Link className="back-link" to="/projects">
        <ArrowLeft size={14} />
        Projects
      </Link>
      <PageTitle
        eyebrow="PROJECTS / CONFIGURATION"
        title={project.data?.name ?? "Project"}
      >
        {project.data?.repo_path}
      </PageTitle>
      {project.data ? (
        <p className="muted">
          <Link
            className="text-link"
            to={`/runs?project_id=${project.data.id}`}
            aria-label={`View tagged Runs ${project.data.id}`}
          >
            View tagged Runs
          </Link>
        </p>
      ) : null}
      <ErrorNotice error={project.error} />
      {project.isPending && <Loading />}
      {project.data && <ProjectWorktrees project={project.data} />}
      {project.data && <ProjectCodingSessions projectId={project.data.id} />}
      {project.data && <ProjectAgents projectId={project.data.id} />}
      {project.data && (
        <div className="image-workspace">
          <section className="panel content-panel">
            <div className="row spread">
              <h2>Project settings</h2>
              <Button
                variant="ghost"
                onClick={() => {
                  setSaved(false);
                  void project.refetch();
                }}
              >
                Reload saved settings
              </Button>
            </div>
            {saved && <p role="status">Project settings saved.</p>}
            <ProjectForm
              key={`${project.data.id}:${project.data.updated_at}:${project.dataUpdatedAt}`}
              project={project.data}
              onSaved={(next) => {
                cache.setQueryData(["project", id], next);
                void cache.invalidateQueries({ queryKey: ["projects"] });
                setSaved(true);
              }}
            />
          </section>
          <aside>
            <section className="panel content-panel">
              <div className="row spread">
                <h2>Working tree</h2>
                <Button
                  variant="secondary"
                  disabled={status.isFetching}
                  onClick={() => void status.refetch()}
                >
                  <RefreshCw size={13} />
                  Refresh
                </Button>
              </div>
              <p className="muted">
                Read-only inspection through the Host Runner.
              </p>
              <ErrorNotice error={status.error} />
              {status.isFetching ? (
                <Loading />
              ) : (
                !status.isError &&
                status.data && (
                  <>
                    <p className="row">
                      <GitBranch size={15} />
                      <strong>{status.data.branch}</strong>
                      <span className="chip">
                        {status.data.dirty ? "Uncommitted changes" : "Clean"}
                      </span>
                    </p>
                    <p className="muted">
                      Checked{" "}
                      {new Date(status.data.checked_at).toLocaleString()}
                    </p>
                    {status.data.porcelain && (
                      <pre className="project-status" aria-label="Git status">
                        {status.data.porcelain}
                      </pre>
                    )}
                  </>
                )
              )}
            </section>
            <section className="panel content-panel">
              <h2>Execution boundary</h2>
              <p>
                Commands, agent rules, and Git policy are saved configuration.
                Worktree preparation creates an isolated branch. Declared Python
                dependencies can be installed into that worktree environment.
                Saved validation commands run inside a native sandbox with
                read-only Git metadata and no network.
              </p>
              <p className="muted">
                If another editor changes this project, reload the saved
                settings before saving again.
              </p>
            </section>
          </aside>
        </div>
      )}
    </>
  );
}
