import { useId } from "react";
import type { RunEvent } from "../api";
import { Badge } from "../components/common";
import { useListKeyboard } from "./useListKeyboard";

function RecordedCommand({ argv }: { argv: unknown }) {
  const recorded = JSON.stringify(argv) ?? "";
  if (recorded.length <= 160) return <pre>{recorded}</pre>;
  const executable =
    Array.isArray(argv) && typeof argv[0] === "string"
      ? argv[0].split(/[\\/]/).pop() || "Command"
      : "Command";
  return (
    <details>
      <summary className="muted">
        <code>{executable}</code> · Full command
      </summary>
      <pre>{recorded}</pre>
    </details>
  );
}

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
              <RecordedCommand argv={event.payload.argv} />
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
                  ? event.payload.ecosystem === "node"
                    ? " · npm registry · lifecycle scripts disabled"
                    : " · PyPI"
                  : " · offline vendor"}
                {event.payload.lock_generated === true
                  ? " · lockfile created offline"
                  : ""}
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
