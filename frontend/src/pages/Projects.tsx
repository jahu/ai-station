import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  FolderGit2,
  GitBranch,
  Plus,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { api } from "../api";
import { Empty, ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";

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
            <option value="claude">Claude Code</option>
            <option value="local">Local model (experimental)</option>
          </select>
          <small className="muted">
            Preference only. Coding execution is not available yet.
          </small>
        </label>
        <details open={Boolean(project)}>
          <summary>Validation commands and agent guidance</summary>
          <div className="project-form-section">
            <p className="muted">
              These trusted commands are saved for future coding Runs. Saving
              does not execute them. Use one JSON argument array per line.
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
          <summary>Future Git workflow policy</summary>
          <div className="project-form-section">
            <p className="muted">
              Stored preferences for future task branches. Force push,
              production PRs, and automatic merge remain disabled.
            </p>
            {(
              [
                ["commit_task_branch", "Allow commits on task branches"],
                ["push_task_branch", "Allow pushing task branches"],
                ["pr_to_integration", "Allow PRs to the integration branch"],
              ] as const
            ).map(([key, label]) => (
              <label className="project-checkbox" key={key}>
                <input
                  type="checkbox"
                  checked={policy[key]}
                  onChange={(e) =>
                    setPolicy({ ...policy, [key]: e.target.checked })
                  }
                />
                {label}
              </label>
            ))}
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
              Register project
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
          <div className="project-grid">
            {projects.data.map((project) => (
              <Link
                className="panel project-card"
                key={project.id}
                to={`/projects/${project.id}`}
              >
                <div className="row spread">
                  <FolderGit2 size={23} />
                  <span className="chip">HOST REPOSITORY</span>
                </div>
                <h2>{project.name}</h2>
                <p className="mono muted">{project.repo_path}</p>
                <div className="project-card-footer">
                  <span>
                    <GitBranch size={13} />
                    {project.integration_branch}
                  </span>
                  <span>{project.preferred_executor} preferred</span>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <section className="panel">
            <Empty title="No projects on this page">
              Register an existing Git repository to inspect its state and
              configure future coding tasks.
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
  return (
    <>
      <Link className="back-link" to="/projects">
        <ArrowLeft size={14} />
        Projects
      </Link>
      <PageTitle eyebrow="PROJECTS / REGISTER" title="Connect a repository">
        The repository stays on your host. Registration reads its Git metadata.
      </PageTitle>
      <div className="image-workspace">
        <section className="panel content-panel">
          <ProjectForm
            onSaved={(project) => {
              void cache.invalidateQueries({ queryKey: ["projects"] });
              navigate(`/projects/${project.id}`);
            }}
          />
        </section>
        <aside className="panel content-panel">
          <ShieldCheck size={22} />
          <h2 className="mt">You control the workflow</h2>
          <p>
            Register a local path inside the runner’s configured roots. Existing
            files and branches stay in place.
          </p>
          <p>
            Coding agents will use isolated task worktrees when that workflow is
            available.
          </p>
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
      <ErrorNotice error={project.error} />
      {project.isPending && <Loading />}
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
                Coding execution and Git writes are not enabled in this
                workspace yet.
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
