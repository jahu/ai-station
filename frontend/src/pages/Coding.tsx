import LlamaModels from "./LlamaModels";
import { Cpu, Cloud, Sparkles, Plus, ArrowUpRight } from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type Run } from "../api";
import { ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import { CodingHistory } from "./CodingSessions";

type Project = {
  id: string;
  name: string;
  updated_at: string;
  preferred_executor?: string;
};
export default function Coding() {
  const navigate = useNavigate();
  const cache = useQueryClient();
  const [params] = useSearchParams();
  const [projectId, setProjectId] = useState(params.get("project") ?? "");
  const [prompt, setPrompt] = useState("");
  const [files, setFiles] = useState("");
  const [model, setModel] = useState("");
  const [approvedScope, setApprovedScope] = useState("");
  const [choice, setChoice] = useState("auto");
  const [explore, setExplore] = useState(true);
  const [repairAttempts, setRepairAttempts] = useState(0);
  const [localModel, setLocalModel] = useState("");
  const [modelPending, setModelPending] = useState(false);
  const projects = useQuery({
    queryKey: ["coding-projects"],
    queryFn: () => api<Project[]>("/projects?limit=500"),
  });
  const project = projects.data?.find((p) => p.id === projectId);
  const preferred = project?.preferred_executor;
  const executor =
    choice === "auto"
      ? ["cursor", "codex", "local"].includes(preferred ?? "")
        ? preferred!
        : "local"
      : choice;
  const scopeKey = JSON.stringify({
    projectId,
    version: project?.updated_at,
    executor,
    explore,
    files: explore ? [] : files,
  });
  const external = approvedScope === scopeKey;
  function setExternal(value: boolean) {
    setApprovedScope(value ? scopeKey : "");
  }
  const local = executor === "local";
  const externalName = executor === "codex" ? "Codex" : "Cursor";
  const provider = useQuery({
    queryKey: ["chat-provider"],
    queryFn: () =>
      api<{ models: string[]; default_model: string }>("/chat/provider"),
    enabled: local,
  });
  const catalog = useQuery({
    queryKey: ["coding-models", executor],
    queryFn: () =>
      api<{ models: { id: string; name: string }[]; notice: string }>(
        `/coding/models/${executor}`,
      ),
    enabled: !local,
    staleTime: 120000,
  });
  const selectedModel = localModel || provider.data?.default_model || "";
  const create = useMutation({
    mutationFn: () =>
      api<Run>(`/coding/${executor}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          expected_updated_at: project?.updated_at,
          prompt,
          files: explore
            ? []
            : files
                .split("\n")
                .map((p) => p.trim())
                .filter(Boolean),
          explore,
          model: local ? selectedModel : model,
          ...(!local
            ? { external_ai: external }
            : { max_repair_attempts: repairAttempts }),
        }),
      }),
    onSuccess: (run) => {
      void cache.invalidateQueries({ queryKey: ["coding-sessions"] });
      navigate(`/coding/${run.task_id}`);
    },
  });
  return (
    <>
      <PageTitle
        eyebrow="WORKSPACE / CODING"
        title="What would you like to build?"
        action={
          <Button variant="secondary" asChild>
            <Link to="/projects/new">
              <Plus size={16} />
              New project
            </Link>
          </Button>
        }
      >
        Pick a project, describe the outcome, and work with your agent in one
        conversation.
      </PageTitle>
      <ErrorNotice error={projects.error ?? create.error} />
      {projects.isPending ? (
        <Loading />
      ) : (
        <div className="coding-start-grid">
          <form
            className="panel content-panel image-form coding-form"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <fieldset disabled={create.isPending || modelPending}>
              <label>
                Project
                <select
                  required
                  value={projectId}
                  onChange={(e) => {
                    setProjectId(e.target.value);
                    setExternal(false);
                    setModel("");
                  }}
                >
                  <option value="">Choose a project</option>
                  {projects.data?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              {!projects.data?.length && (
                <p className="notice">
                  Start with a name — we’ll prepare the folder, Git repository
                  and Python environment.{" "}
                  <Link className="text-link" to="/projects/new">
                    Create your first project →
                  </Link>
                </p>
              )}
              <div
                className="coding-executor-options coding-agent-options"
                role="group"
                aria-label="Coding executor"
              >
                {[
                  ["auto", "Auto", Sparkles],
                  ["local", "Local AI", Cpu],
                  ["cursor", "Cursor", Cloud],
                  ["codex", "Codex", Cloud],
                ].map(([id, title, Icon]) => {
                  const Symbol = Icon as typeof Cpu;
                  return (
                    <button
                      type="button"
                      key={String(id)}
                      aria-label={String(title)}
                      aria-pressed={choice === id}
                      onClick={() => {
                        setChoice(String(id));
                        setExternal(false);
                        setModel("");
                      }}
                    >
                      <Symbol size={18} />
                      <span>
                        <strong>{String(title)}</strong>
                        <small>
                          {id === "auto"
                            ? "Project preference"
                            : id === "local"
                              ? "On this machine"
                              : "External AI"}
                        </small>
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="coding-model-row">
                <span className="chip">
                  {local
                    ? "LOCAL AI"
                    : externalName.toUpperCase() + " · EXTERNAL"}
                </span>
                {local ? (
                  <div className="coding-local-model">
                    <span>Model</span>
                    <LlamaModels
                      coding
                      value={selectedModel}
                      models={provider.data?.models ?? []}
                      busy={create.isPending}
                      onSelect={setLocalModel}
                      onBusy={setModelPending}
                    />
                    <small className="muted">
                      Managed llama.cpp prepares a 128k Coding context with Q8
                      KV cache. Local-server context is configured separately.
                    </small>
                  </div>
                ) : (
                  <label>
                    Model
                    <select
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                    >
                      <option value="">Auto — provider default</option>
                      {catalog.data?.models
                        .filter((m) => m.id !== "auto")
                        .map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                          </option>
                        ))}
                    </select>
                  </label>
                )}
              </div>
              <ErrorNotice error={local ? provider.error : catalog.error} />
              {!local && catalog.data?.notice && (
                <small className="muted">{catalog.data.notice}</small>
              )}
              <label>
                Task
                <textarea
                  required
                  maxLength={10000}
                  rows={6}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Build a website for my studio. Start with a homepage and a contact form…"
                />
              </label>
              <details className="coding-advanced">
                <summary>Advanced settings</summary>
                <div className="coding-advanced-fields">
                  <label className="project-checkbox">
                    <input
                      type="checkbox"
                      checked={explore}
                      onChange={(e) => {
                        setExplore(e.target.checked);
                        setExternal(false);
                      }}
                    />
                    Let the agent find the relevant files
                  </label>
                  {!explore && (
                    <label>
                      Files the agent may edit
                      <textarea
                        required
                        rows={3}
                        value={files}
                        onChange={(e) => {
                          setFiles(e.target.value);
                          setExternal(false);
                        }}
                        placeholder="src/app.py&#10;README.md"
                      />
                      <small>
                        Relative paths, one per line. You can include new files.
                      </small>
                    </label>
                  )}
                  {local && (
                    <label>
                      Repair after failed checks
                      <select
                        value={repairAttempts}
                        onChange={(e) =>
                          setRepairAttempts(Number(e.target.value))
                        }
                      >
                        <option value={0}>Ask me first</option>
                        <option value={1}>One attempt</option>
                        <option value={2}>Up to two attempts</option>
                      </select>
                    </label>
                  )}
                  <Link
                    className="text-link"
                    to={project ? `/projects/${project.id}` : "/projects"}
                  >
                    Project settings: branches, checks and rules{" "}
                    <ArrowUpRight size={13} />
                  </Link>
                </div>
              </details>
              {!local && (
                <label className="project-checkbox">
                  <input
                    type="checkbox"
                    checked={external}
                    onChange={(e) => setExternal(e.target.checked)}
                    required
                  />
                  <span>
                    Allow {externalName} to receive this conversation, project
                    guidance and{" "}
                    {explore
                      ? "relevant source files found by the agent"
                      : "the selected files"}
                    .
                  </span>
                </label>
              )}
              <Button
                type="submit"
                disabled={
                  !project ||
                  !prompt.trim() ||
                  (local ? !selectedModel || modelPending : !external)
                }
              >
                {create.isPending ? "Preparing workspace…" : "Start coding"}
                <ArrowUpRight size={16} />
              </Button>
              <small className="muted">
                Changes stay in a separate workspace. Return here for follow-up
                instructions and review before committing.
              </small>
            </fieldset>
          </form>
          <aside className="coding-recent">
            <h2>Your coding conversations</h2>
            <p className="muted">Pick up where you left off.</p>
            <CodingHistory />
          </aside>
        </div>
      )}
    </>
  );
}
