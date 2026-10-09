import { useId } from "react";
import type { RunEvent } from "../api";
import { Badge } from "../components/common";
import { useListKeyboard } from "./useListKeyboard";

export function ValidationResults({ events }: { events: RunEvent[] }) {
  const headingId = useId();
  const labelId = useId();
  const results = events.filter(
    (event) => event.event_type === "validation.completed",
  );
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    results,
    (event) => event.id,
  );
  if (!results.length) return null;
  return (
    <section className="panel content-panel" aria-labelledby={headingId}>
      <h2 id={headingId}>Project validation</h2>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a validation command while the list is focused. There
        is no inspectable child Run; logs stay on this Run.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {results.map((event, i) => (
          <article
            key={event.id}
            aria-label={`Command ${String(event.payload.kind)} ${event.id}`}
            {...itemProps(i, event.id)}
          >
            <div>
              <strong>{String(event.payload.kind)}</strong>
              <pre>{JSON.stringify(event.payload.argv)}</pre>
              <p className="muted">
                Exit {String(event.payload.exit_code)} ·{" "}
                {String(event.payload.duration_seconds)} seconds
              </p>
            </div>
            <Badge
              status={event.payload.exit_code === 0 ? "succeeded" : "failed"}
            />
          </article>
        ))}
      </div>
    </section>
  );
}

export function DependencyResults({ events }: { events: RunEvent[] }) {
  const headingId = useId();
  const labelId = useId();
  const results = events.filter(
    (event) => event.event_type === "dependencies.completed",
  );
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    results,
    (event) => event.id,
  );
  if (!results.length) return null;
  return (
    <section className="panel content-panel" aria-labelledby={headingId}>
      <h2 id={headingId}>Project dependencies</h2>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a dependency install while the list is focused. There
        is no inspectable child Run; the JSON report stays on this Run.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {results.map((event, i) => (
          <article
            key={event.id}
            aria-label={`Install ${String(event.payload.manifest)} ${event.id}`}
            {...itemProps(i, event.id)}
          >
            <div>
              <strong>
                {String(event.payload.manifest)} ·{" "}
                {String(event.payload.source)}
              </strong>
              <pre>{JSON.stringify(event.payload.specifiers)}</pre>
              <p className="muted">
                Exit {String(event.payload.exit_code)} ·{" "}
                {String(event.payload.duration_seconds)} seconds
                {event.payload.network === true
                  ? " · PyPI"
                  : " · offline vendor"}
              </p>
            </div>
            <Badge
              status={event.payload.exit_code === 0 ? "succeeded" : "failed"}
            />
          </article>
        ))}
      </div>
    </section>
  );
}
