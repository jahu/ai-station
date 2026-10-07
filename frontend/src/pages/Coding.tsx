import LlamaModels from "./LlamaModels";
import { Cpu, Cloud } from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api, type Run } from "../api";
import { ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";

type Project = {
  id: string;
  name: string;
  updated_at: string;
  integration_branch: string;
};

export default function Coding() {
  const navigate = useNavigate();
  const [projectId, setProjectId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [files, setFiles] = useState("README.md");
  const [model, setModel] = useState("");
  const [external, setExternal] = useState(false);
  const [executor, setExecutor] = useState("cursor");
  const [explore, setExplore] = useState(true);
  const [repairAttempts, setRepairAttempts] = useState(0);
  const [localModel, setLocalModel] = useState("");
  const [modelPending, setModelPending] = useState(false);
  const provider = useQuery({
    queryKey: ["chat-provider"],
    queryFn: () =>
      api<{ models: string[]; default_model: string }>("/chat/provider"),
    enabled: executor === "local",
  });
  const selectedModel = localModel || provider.data?.default_model || "";
  const local = executor === "local";
  const projects = useQuery({
    queryKey: ["coding-projects"],
    queryFn: () => api<Project[]>("/projects?limit=500"),
  });
  const project = projects.data?.find((p) => p.id === projectId);
  const create = useMutation({
    mutationFn: () =>
      api<Run>(`/coding/${executor}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          expected_updated_at: project?.updated_at,
          prompt,
          files:
            local && explore
              ? []
              : files
                  .split("\n")
                  .map((p) => p.trim())
                  .filter(Boolean),
          model: local ? selectedModel : model,
          ...(!local
            ? { external_ai: external }
            : { explore, max_repair_attempts: repairAttempts }),
        }),
      }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });
  return (
    <>
      <PageTitle eyebrow="CODING / CONTROLLED WORKSPACE" title="Coding task">
        Propose source changes in a fresh task worktree, then inspect validation
        and the diff.
      </PageTitle>
      <ErrorNotice
        error={
          projects.error ?? create.error ?? (local ? provider.error : null)
        }
      />
      {projects.isPending ? (
        <Loading />
      ) : (
        <div className="image-workspace">
          <form
            className="panel content-panel image-form coding-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (!modelPending) create.mutate();
            }}
          >
            <fieldset disabled={create.isPending || modelPending}>
              <div
                className="coding-executor-options"
                role="group"
                aria-label="Coding executor"
              >
                <button
                  type="button"
                  aria-label="Local AI llama.cpp or local server"
                  aria-pressed={local}
                  onClick={() => {
                    setExecutor("local");
                    setExternal(false);
                  }}
                >
                  <Cpu size={19} />
                  <span>
                    <strong>Local AI</strong>
                    <small>llama.cpp / local server</small>
                  </span>
                </button>
                <button
                  type="button"
                  aria-pressed={!local}
                  onClick={() => setExecutor("cursor")}
                >
                  <Cloud size={19} />
                  <span>
                    <strong>Cursor</strong>
                    <small>External AI · explicit consent</small>
                  </span>
                </button>
              </div>
              <label>
                Project
                <select
                  aria-label="Project"
                  required
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                >
                  <option value="">Select a registered project</option>
                  {projects.data?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Task
                <textarea
                  required
                  maxLength={10000}
                  rows={5}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Describe the change and its acceptance criteria"
                />
              </label>
              {local && (
                <label className="project-checkbox">
                  <input
                    type="checkbox"
                    checked={explore}
                    onChange={(e) => setExplore(e.target.checked)}
                  />
                  Let Local AI find the relevant files
                </label>
              )}
              {local && (
                <label>
                  Automatic repair
                  <select
                    value={repairAttempts}
                    onChange={(event) =>
                      setRepairAttempts(Number(event.target.value))
                    }
                  >
                    <option value={0}>Off — I will request repairs</option>
                    <option value={1}>Try once if validation fails</option>
                    <option value={2}>
                      Try up to twice if validation fails
                    </option>
                  </select>
                  <small>
                    Uses the same local model and files. Saved checks run after
                    each attempt. Stops on cancellation or execution failure;
                    committing always requires review.
                  </small>
                </label>
              )}
              {local && explore ? (
                <p className="notice">
                  The model can list, search and read source files inside its
                  new worktree. It selects the files to edit; you review the
                  resulting diff and tests.
                </p>
              ) : (
                <>
                  <label>
                    Selected files
                    <textarea
                      required
                      rows={4}
                      value={files}
                      onChange={(e) => setFiles(e.target.value)}
                    />
                  </label>
                  <p className="muted">
                    One relative path per line, up to ten UTF-8 source files.
                    New paths are allowed. Hidden configuration and credential
                    paths are excluded; existing content is limited to 32 KB per
                    file and 64 KB total.
                  </p>
                </>
              )}
              {local ? (
                <LlamaModels
                  value={selectedModel}
                  models={provider.data?.models ?? []}
                  busy={create.isPending}
                  onSelect={setLocalModel}
                  onBusy={setModelPending}
                />
              ) : (
                <>
                  <label>
                    Cursor model
                    <input
                      value={model}
                      maxLength={100}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="Auto (default)"
                    />
                  </label>
                  <label className="project-checkbox">
                    <input
                      type="checkbox"
                      checked={external}
                      onChange={(e) => setExternal(e.target.checked)}
                      required
                    />
                    Allow sending this task, project guidance and selected file
                    contents to external Cursor AI.
                  </label>
                </>
              )}
              <Button
                type="submit"
                disabled={
                  !project ||
                  (local ? !selectedModel || modelPending : !external) ||
                  !prompt.trim()
                }
              >
                {create.isPending
                  ? "Queueing…"
                  : local
                    ? "Create worktree and start Local AI"
                    : "Create worktree and start Cursor"}
              </Button>
            </fieldset>
          </form>
          <aside className="panel content-panel">
            <span className="chip">
              {local
                ? "LOCAL AI · HOST EXECUTION"
                : "EXTERNAL AI · HOST EXECUTION"}
            </span>
            <h2 className="mt">Review before integration</h2>
            <p>
              A new branch starts from{" "}
              {project?.integration_branch ??
                "the project's integration branch"}
              .{" "}
              {local && explore
                ? "Your local model explores source files using bounded read-only tools, then proposes changes."
                : "The model proposes changes to your selected files with tools disabled."}{" "}
              AI Station checks each replacement before applying it in the new
              worktree.
            </p>
            <p>
              Saved test, lint and build commands run afterward in the native
              sandbox. Successful generation means the proposal was applied;
              inspect the separate validation Run and diff before accepting it.
            </p>
            <p>
              The original checkout stays intact. After successful validation,
              you can review and commit the selected changes to the task branch.
              Push, merge and deployment remain separate.
            </p>
            <p className="muted">
              {local && explore
                ? "Repository exploration stays local. Hidden configuration, credentials and symlink escapes are excluded. Exploration steps appear with the review."
                : "The model can change only the files listed here. Add new file paths before starting."}
            </p>
            <Link className="text-link" to="/projects">
              Configure projects and validation commands →
            </Link>
          </aside>
        </div>
      )}
    </>
  );
}
