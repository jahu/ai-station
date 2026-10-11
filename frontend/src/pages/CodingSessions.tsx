import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";
import {
  ChevronDown,
  Code2,
  Plus,
  ArrowUpRight,
  Send,
  Square,
} from "lucide-react";
import { api, type Run } from "../api";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  PageTitle,
} from "../components/common";
import { Button } from "../components/ui/button";
import { terminal, time } from "../lib/utils";
import CodingReview from "./CodingReview";
import GithubPublication from "./GithubPublication";
import { ConsentChoiceList } from "./ConsentChoiceList";
import { useListKeyboard } from "./useListKeyboard";

type SessionRow = {
  id: string;
  title: string;
  project_id?: string | null;
  project_name: string;
  status: string;
  active_run_id: string | null;
  latest_proposal_id: string | null;
};
function useSessions(offset = 0) {
  return useQuery({
    queryKey: ["coding-sessions", offset],
    queryFn: () =>
      api<SessionRow[]>(`/coding/sessions${offset ? `?offset=${offset}` : ""}`),
    refetchInterval: 10000,
  });
}
function SessionCards({ sessions }: { sessions: SessionRow[] }) {
  const headingId = useId();
  const labelId = useId();
  const navigate = useNavigate();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    sessions,
    (session) => session.id,
  );
  const selected = sessions[index];
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key !== "Enter" || event.defaultPrevented) return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, select")) return;
    if (selected?.id) {
      event.preventDefault();
      navigate(`/coding/${selected.id}`);
    }
  };
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="sr-only">
        Coding conversations
      </h2>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a conversation while the list is focused. Enter opens
        it. Inspect project stays on a saved project and does not start a coding
        Run.
      </p>
      <div
        ref={listRef}
        className="coding-history"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {sessions.map((s, i) => {
          const current = i === index;
          const shortId = s.id.slice(0, 8);
          return (
            <article
              className="panel coding-history-item"
              key={s.id}
              {...itemProps(i, s.id)}
              onClick={(event) => {
                if (
                  (event.target as HTMLElement).closest(
                    "a, button, textarea, input, select",
                  )
                )
                  return;
                navigate(`/coding/${s.id}`);
              }}
            >
              <span className="row spread">
                {s.project_id ? (
                  <Link
                    className="text-link"
                    to={`/projects/${s.project_id}`}
                    tabIndex={current ? 0 : -1}
                    aria-label={`Inspect project ${s.project_id}`}
                    onClick={(event) => event.stopPropagation()}
                  >
                    {s.project_name}
                  </Link>
                ) : (
                  <small>{s.project_name}</small>
                )}
                <Badge status={s.status} />
              </span>
              <Link
                className="text-link"
                to={`/coding/${s.id}`}
                tabIndex={current ? 0 : -1}
                aria-label={`Inspect ${s.title} ${shortId}`}
              >
                <strong>{s.title}</strong>
              </Link>
              <span className="text-link">
                Open conversation <ArrowUpRight size={13} aria-hidden="true" />
              </span>
            </article>
          );
        })}
      </div>
    </section>
  );
}
export function CodingHistory() {
  const [offset, setOffset] = useState(0);
  const q = useSessions(offset);
  return (
    <>
      <ErrorNotice error={q.error} />
      {q.isPending ? (
        <Loading />
      ) : q.data?.length ? (
        <SessionCards sessions={q.data} />
      ) : (
        <Empty title="A fresh start">
          Your tasks and follow-up conversations will appear here.
        </Empty>
      )}
      <div className="row mt">
        <Button
          variant="secondary"
          disabled={!offset}
          onClick={() => setOffset(Math.max(0, offset - 30))}
        >
          Newer
        </Button>
        <small className="muted">Page {offset / 30 + 1}</small>
        <Button
          variant="secondary"
          disabled={q.isPending || q.data?.length !== 30}
          onClick={() => setOffset(offset + 30)}
        >
          Older
        </Button>
      </div>
    </>
  );
}
export function CodingNav() {
  const [open, setOpen] = useState(true);
  const q = useSessions();
  return (
    <div className="coding-nav">
      <div className="coding-nav-heading">
        <NavLink to="/coding">
          <Code2 size={17} />
          Coding
        </NavLink>
        <button
          aria-label="Toggle coding conversations"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          <ChevronDown
            size={14}
            style={{ transform: open ? undefined : "rotate(-90deg)" }}
          />
        </button>
      </div>
      {open && (
        <div className="coding-nav-tasks">
          <NavLink end to="/coding">
            <Plus size={12} />
            New conversation
          </NavLink>
          {q.data?.slice(0, 12).map((s) => (
            <NavLink
              key={s.id}
              to={`/coding/${s.id}`}
              title={`${s.project_name}: ${s.title}`}
            >
              <span className={`status-dot ${s.active_run_id ? "" : "idle"}`} />
              <span>{s.title}</span>
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}
export default function CodingSession() {
  const { id } = useParams();
  const cache = useQueryClient();
  const [prompt, setPrompt] = useState("");
  const [external, setExternal] = useState(false);
  const q = useQuery({
    queryKey: ["coding-session", id],
    queryFn: () => api<SessionRow & { runs: Run[] }>(`/coding/sessions/${id}`),
    refetchInterval: 2000,
  });
  const runs = q.data?.runs ?? [];
  const proposals = runs.filter((r) =>
    ["cursor_proposal", "codex_proposal", "local_proposal"].includes(
      r.executor_type,
    ),
  );
  const latest = proposals.at(-1);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [proposals.length]);
  const active = [...runs].reverse().find((r) => !terminal.has(r.status));
  const isExternal = latest?.metadata?.execution_location === "external";
  const send = useMutation({
    mutationFn: () =>
      api<Run>(`/coding/sessions/${id}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          expected_run_id: latest?.id,
          external_ai: external,
        }),
      }),
    onSuccess: () => {
      setPrompt("");
      setExternal(false);
      void cache.invalidateQueries({ queryKey: ["coding-session", id] });
      void cache.invalidateQueries({ queryKey: ["coding-sessions"] });
    },
  });
  const cancel = useMutation({
    mutationFn: () => api(`/runs/${active?.id}/cancel`, { method: "POST" }),
    onSuccess: () =>
      void cache.invalidateQueries({ queryKey: ["coding-session", id] }),
  });
  return (
    <>
      <PageTitle
        eyebrow={q.data?.project_name ?? "CODING"}
        title={q.data?.title ?? "Coding conversation"}
        action={
          <Button variant="secondary" asChild>
            <Link to="/coding">
              <Plus size={15} />
              New conversation
            </Link>
          </Button>
        }
      >
        Your instructions, the agent’s results and the same workspace across
        every turn.
        {q.data?.project_id ? (
          <p className="mt">
            <Link
              className="text-link"
              to={`/projects/${q.data.project_id}`}
              aria-label={`Inspect project ${q.data.project_id}`}
            >
              {q.data.project_name}
            </Link>
          </p>
        ) : null}
      </PageTitle>
      <ErrorNotice error={q.error ?? send.error ?? cancel.error} />
      {q.isPending ? (
        <Loading />
      ) : (
        q.data && (
          <div className="coding-conversation">
            <div className="coding-turns">
              {!proposals.length && (
                <div className="panel content-panel">
                  <p>Preparing your workspace…</p>
                  {runs.map((r) => (
                    <Link className="text-link" key={r.id} to={`/runs/${r.id}`}>
                      {r.status} · Inspect setup →
                    </Link>
                  ))}
                </div>
              )}
              {proposals.map((r) => (
                <article className="coding-turn" key={r.id}>
                  <div className="coding-instruction">
                    <small>You · {time(r.created_at)}</small>
                    <p>
                      {String(
                        r.parameters.user_prompt ??
                          r.parameters.original_prompt ??
                          r.parameters.prompt ??
                          "",
                      )}
                    </p>
                  </div>
                  <div className="panel content-panel coding-answer">
                    <div className="row spread">
                      <strong>
                        {r.executor_type === "local_proposal"
                          ? "Local AI"
                          : r.executor_type === "codex_proposal"
                            ? "Codex"
                            : "Cursor"}
                      </strong>
                      <Badge status={r.status} />
                    </div>
                    <p>
                      {r.summary ||
                        r.error_message ||
                        (!terminal.has(r.status)
                          ? "Working on your request…"
                          : "No completed result. Inspect execution details below.")}
                    </p>
                    <Link className="text-link" to={`/runs/${r.id}`}>
                      Execution details and logs <ArrowUpRight size={13} />
                    </Link>
                    {r.id === latest?.id &&
                      r.metadata?.coding_review !== undefined && (
                        <details className="coding-inline-review">
                          <summary>Review changed files and validation</summary>
                          <CodingReview run={r} />
                        </details>
                      )}
                  </div>
                </article>
              ))}
              {runs
                .filter(
                  (r) =>
                    r.executor_type === "project_validation" ||
                    r.executor_type === "project_dependencies" ||
                    r.executor_type === "reviewed_commit" ||
                    r.executor_type === "github_publication",
                )
                .map((r) => (
                  <details key={r.id} className="panel coding-check-result">
                    <summary>
                      <Badge status={r.status} />
                      {r.executor_type === "project_validation"
                        ? "Project checks"
                        : r.executor_type === "project_dependencies"
                          ? "Project dependencies"
                          : r.executor_type === "reviewed_commit"
                            ? "Reviewed commit"
                            : "GitHub publication"}
                    </summary>
                    <p>{r.summary || r.error_message}</p>
                    <Link className="text-link" to={`/runs/${r.id}`}>
                      Inspect result →
                    </Link>
                    {r.executor_type === "reviewed_commit" && (
                      <GithubPublication run={r} />
                    )}
                  </details>
                ))}
              <div ref={end} />
            </div>
            <form
              className="panel coding-reply"
              onSubmit={(e) => {
                e.preventDefault();
                send.mutate();
              }}
            >
              <div className="row spread">
                <strong>
                  {active ? "Agent is working" : "Continue the conversation"}
                </strong>
                {active && (
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={cancel.isPending}
                    onClick={() => cancel.mutate()}
                  >
                    <Square size={12} />
                    Stop
                  </Button>
                )}
              </div>
              <textarea
                aria-label="Follow-up instruction"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                maxLength={4000}
                rows={3}
                placeholder="What should we change or build next?"
                disabled={!!active || !latest}
              />
              {isExternal && (
                <ConsentChoiceList
                  checked={external}
                  disabled={!!active || send.isPending}
                  labelClassName="coding-turn-consent"
                  onChange={setExternal}
                >
                  <span>
                    Share this turn and relevant source with{" "}
                    {latest?.executor_type === "codex_proposal"
                      ? "Codex"
                      : "Cursor"}
                    .
                  </span>
                </ConsentChoiceList>
              )}
              <div className="row spread">
                <small className="muted">
                  Same project · same workspace · history preserved
                </small>
                <Button
                  disabled={
                    !!active ||
                    !latest ||
                    !prompt.trim() ||
                    send.isPending ||
                    (isExternal && !external)
                  }
                >
                  <Send size={14} />
                  {send.isPending ? "Sending…" : "Send"}
                </Button>
              </div>
            </form>
          </div>
        )
      )}
    </>
  );
}
