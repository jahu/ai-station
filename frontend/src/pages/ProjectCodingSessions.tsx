import { useId, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Badge, Empty, ErrorNotice, Loading } from "../components/common";
import { time } from "../lib/utils";
import { useListKeyboard } from "./useListKeyboard";

interface CodingSession {
  id: string;
  title: string;
  status: string;
  updated_at: string;
}

function SessionCards({
  sessions,
  projectId,
}: {
  sessions: CodingSession[];
  projectId: string;
}) {
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
    if (target.closest("a, button, textarea, input")) return;
    if (selected?.id) {
      event.preventDefault();
      navigate(`/coding/${selected.id}`);
    }
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a conversation while the list is focused. Enter opens
        it. View tagged Runs stays on the selected row. This list does not
        start a coding Run.
      </p>
      <div
        ref={listRef}
        className="worktree-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {sessions.map((session, i) => {
          const current = i === index;
          const shortId = session.id.slice(0, 8);
          return (
            <article key={session.id} {...itemProps(i, session.id)}>
              <div className="row spread">
                <Link
                  className="text-link"
                  to={`/coding/${session.id}`}
                  tabIndex={current ? 0 : -1}
                  aria-label={`Inspect ${session.title} ${shortId}`}
                >
                  {session.title}
                </Link>
                <Badge status={session.status} />
              </div>
              <p className="muted">{time(session.updated_at)}</p>
              <Link
                className="text-link"
                to={`/runs?project_id=${projectId}`}
                tabIndex={current ? 0 : -1}
                aria-label={`View tagged Runs ${shortId}`}
              >
                View tagged Runs
              </Link>
            </article>
          );
        })}
      </div>
    </>
  );
}

export default function ProjectCodingSessions({
  projectId,
}: {
  projectId: string;
}) {
  const headingId = useId();
  const sessions = useQuery({
    queryKey: ["project-coding-sessions", projectId],
    queryFn: () =>
      api<CodingSession[]>(
        `/coding/sessions?limit=50&offset=0&project_id=${encodeURIComponent(projectId)}`,
      ),
  });
  const rows = Array.isArray(sessions.data) ? sessions.data : [];
  return (
    <section className="panel content-panel mt" aria-labelledby={headingId}>
      <div className="row spread">
        <h2 id={headingId}>Coding conversations</h2>
        <Link
          className="text-link"
          to={`/coding?project_id=${projectId}`}
          aria-label="View all coding conversations"
        >
          View all coding conversations
        </Link>
      </div>
      <p className="muted">
        Persistent coding Tasks for this project. Opening a conversation does
        not start a coding Run. View tagged Runs stays on the selected row.
      </p>
      <ErrorNotice error={sessions.error} />
      {sessions.isPending ? (
        <Loading />
      ) : rows.length ? (
        <SessionCards sessions={rows} projectId={projectId} />
      ) : (
        <Empty title="No coding conversations">
          Start a coding conversation from Coding to continue work on this
          project.
        </Empty>
      )}
    </section>
  );
}
