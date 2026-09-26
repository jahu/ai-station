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
  const projects = useQuery({
    queryKey: ["coding-projects"],
    queryFn: () => api<Project[]>("/projects?limit=500"),
  });
  const project = projects.data?.find((p) => p.id === projectId);
  const create = useMutation({
    mutationFn: () =>
      api<Run>("/coding/cursor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          expected_updated_at: project?.updated_at,
          prompt,
          files: files
            .split("\n")
            .map((p) => p.trim())
            .filter(Boolean),
          model,
          external_ai: external,
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
      <ErrorNotice error={projects.error ?? create.error} />
      {projects.isPending ? (
        <Loading />
      ) : (
        <div className="image-workspace">
          <form
            className="panel content-panel image-form"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <fieldset disabled={create.isPending}>
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
                One relative path per line, up to ten UTF-8 source files. New
                paths are allowed. Hidden configuration and credential paths are
                excluded; existing content is limited to 32 KB per file and 64
                KB total.
              </p>
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
              <Button
                type="submit"
                disabled={!project || !external || !prompt.trim()}
              >
                {create.isPending
                  ? "Queueing…"
                  : "Create worktree and start Cursor"}
              </Button>
            </fieldset>
          </form>
          <aside className="panel content-panel">
            <span className="chip">EXTERNAL AI · HOST EXECUTION</span>
            <h2 className="mt">Review before integration</h2>
            <p>
              A new branch starts from{" "}
              {project?.integration_branch ??
                "the project's integration branch"}
              . Cursor proposes file replacements with tools disabled. AI
              Station checks and applies them only to the selected paths in the
              new worktree.
            </p>
            <p>
              Saved test, lint and build commands run afterward in the native
              sandbox. Successful generation means the proposal was applied;
              inspect the separate validation Run and diff before accepting it.
            </p>
            <p>
              The original checkout stays intact. No commit, push, merge or
              deployment is performed.
            </p>
            <p className="muted">
              This first adapter supports text replacements, not repository
              exploration, file deletion or arbitrary agent commands. Codex,
              Claude Code and local coding adapters remain unavailable.
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
