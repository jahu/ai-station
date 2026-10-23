import { useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";

type CodingTask = {
  id: string;
  title: string;
  project_name: string;
  status: string;
  latest_proposal_id: string | null;
};

export default function ChatWorkPicker({
  conversationId,
  settingsVersion,
  selectedTask,
  busy,
  onBusyChange,
  onSelected,
}: {
  conversationId: string;
  settingsVersion: number;
  selectedTask?: string;
  busy: boolean;
  onBusyChange: (pending: boolean) => void;
  onSelected: () => void;
}) {
  const cache = useQueryClient();
  const panelId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const tasks = useQuery({
    queryKey: ["work-coding-tasks", query, offset],
    enabled: open,
    queryFn: () =>
      api<CodingTask[]>(
        `/coding/sessions?q=${encodeURIComponent(query)}&limit=20&offset=${offset}`,
      ),
  });
  const select = useMutation({
    mutationFn: (task: CodingTask | null) =>
      api<{ work_context: unknown; settings_version: number }>(
        `/chat/conversations/${conversationId}/work-context`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            task_id: task?.id ?? null,
            expected_run_id: task?.latest_proposal_id ?? null,
            expected_settings_version: settingsVersion,
          }),
        },
      ),
    onMutate: () => onBusyChange(true),
    onSuccess: async (result) => {
      cache.setQueryData(
        ["conversation", conversationId],
        (current: Record<string, unknown> | undefined) =>
          current ? { ...current, ...result } : current,
      );
      onSelected();
      setOpen(false);
      await cache.invalidateQueries({
        queryKey: ["conversation", conversationId],
      });
    },
    onSettled: () => onBusyChange(false),
  });
  const disabled = busy || select.isPending;
  return (
    <section className="work-task-picker" aria-label="Continue a project task">
      <Button
        type="button"
        variant="ghost"
        ref={trigger}
        aria-expanded={open}
        aria-controls={panelId}
        disabled={disabled}
        onClick={() => setOpen(!open)}
      >
        {open
          ? "Close task picker"
          : selectedTask
            ? "Change project task"
            : "Continue a project task"}
      </Button>
      {open && (
        <div
          className="work-context-card"
          id={panelId}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              setOpen(false);
              trigger.current?.focus();
            }
          }}
        >
          <div className="row spread">
            <strong>Continue an existing workspace</strong>
            <Button
              type="button"
              variant="ghost"
              disabled={disabled}
              onClick={() => select.mutate(null)}
            >
              General Work
            </Button>
          </div>
          <p className="muted">
            Optionally continue a project task with its files and agent. You can
            use Work without selecting one. Selection does not start work.
          </p>
          <input
            aria-label="Find coding task or project"
            placeholder="Search tasks or projects…"
            value={query}
            disabled={disabled}
            onChange={(event) => {
              setQuery(event.target.value);
              setOffset(0);
            }}
          />
          {tasks.isPending && <Loading />}
          <ErrorNotice error={tasks.error} />
          <div className="work-task-options">
            {tasks.data?.map((task) => (
              <div className="row spread" key={task.id}>
                <Button
                  type="button"
                  variant={selectedTask === task.id ? "secondary" : "ghost"}
                  disabled={disabled || !task.latest_proposal_id}
                  aria-label={`Continue ${task.title} in ${task.project_name}`}
                  onClick={() => select.mutate(task)}
                >
                  <span>
                    <strong>{task.title}</strong>
                    <span className="muted">
                      {task.project_name} · {task.status}
                    </span>
                  </span>
                </Button>
                <Link
                  to={`/coding/${task.id}`}
                  aria-label={`Inspect ${task.title}`}
                >
                  Workspace
                </Link>
              </div>
            ))}
          </div>
          {tasks.data?.length === 0 && (
            <p className="muted">
              No matching project tasks. You can use Work without choosing a
              project.
            </p>
          )}
          <div className="row spread">
            <Button
              type="button"
              variant="ghost"
              disabled={disabled || !offset}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={
                disabled || tasks.isFetching || tasks.data?.length !== 20
              }
              onClick={() => setOffset(offset + 20)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
      <ErrorNotice error={select.error} />
    </section>
  );
}
