import { useState } from "react";
import type { RunEvent } from "../api";
import { Button } from "../components/ui/button";

const outputTypes = new Set(["stdout", "stderr", "chat.delta", "agent.delta"]);
const pageSize = 50;
type View = "activity" | "output" | "all";

export default function RunTimeline({
  events,
  live,
}: {
  events: RunEvent[];
  live: boolean;
}) {
  const [view, setView] = useState<View>("activity");
  // Sequence boundaries keep an older page stable while new events arrive.
  const [boundaries, setBoundaries] = useState<number[]>([]);
  const filtered =
    view === "activity"
      ? events.filter((e) => !outputTypes.has(e.event_type))
      : events;
  const before = boundaries.at(-1);
  const end =
    before === undefined
      ? filtered.length
      : filtered.findIndex((e) => e.sequence >= before);
  const start = Math.max(0, end - pageSize);
  const page = filtered.slice(start, end);
  const output =
    view === "output"
      ? events.filter((e) => outputTypes.has(e.event_type))
      : [];
  const text = output
    .map((e, index) => {
      const prefix =
        output[index - 1]?.event_type === e.event_type
          ? ""
          : `\n[${e.event_type}]\n`;
      return (
        prefix +
        (typeof e.payload.text === "string"
          ? e.payload.text
          : JSON.stringify(e.payload))
      );
    })
    .join("");
  return (
    <section className="panel run-timeline">
      <div className="panel-heading">
        <h2>Execution timeline</h2>
        <span className="muted">
          {live ? "Live events" : "Recorded events"} · {events.length}
        </span>
      </div>
      <div className="run-event-controls" role="group" aria-label="Event view">
        {(
          [
            ["activity", "Activity"],
            ["output", "Output"],
            ["all", "All events"],
          ] as const
        ).map(([key, label]) => (
          <Button
            key={key}
            variant={view === key ? "default" : "secondary"}
            aria-pressed={view === key}
            onClick={() => {
              setView(key);
              setBoundaries([]);
            }}
          >
            {label}
          </Button>
        ))}
      </div>
      {view === "output" ? (
        <div className="run-output">
          <p className="muted">
            Captured output in execution order. Structured actions remain in
            Activity.
          </p>
          <pre tabIndex={0} aria-label="Captured output">
            {text || "No output recorded yet."}
          </pre>
        </div>
      ) : (
        <>
          <p className="muted run-event-count">
            {filtered.length
              ? `${start + 1}–${end} of ${filtered.length} ${view === "activity" ? "activity" : "total"} events`
              : "No events in this view yet."}
            {view === "activity" &&
              " · Token and process output is grouped in Output."}
          </p>
          <div
            className="timeline run-event-list"
            tabIndex={0}
            aria-label="Execution events"
          >
            {page.map((event) => (
              <article key={event.id}>
                <span className="timeline-node" />
                <div className="row spread">
                  <strong>{event.event_type}</strong>
                  <time dateTime={event.created_at}>
                    #{event.sequence} ·{" "}
                    {new Date(event.created_at).toLocaleTimeString()}
                  </time>
                </div>
                <pre>
                  {typeof event.payload.text === "string"
                    ? event.payload.text
                    : JSON.stringify(event.payload, null, 2)}
                </pre>
              </article>
            ))}
          </div>
          <div className="run-event-controls">
            <Button
              variant="secondary"
              disabled={start === 0}
              onClick={() => setBoundaries([...boundaries, page[0].sequence])}
            >
              Older events
            </Button>
            <Button
              variant="secondary"
              disabled={!boundaries.length}
              onClick={() => setBoundaries(boundaries.slice(0, -1))}
            >
              Newer events
            </Button>
            {!!boundaries.length && (
              <Button variant="secondary" onClick={() => setBoundaries([])}>
                Latest events
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
