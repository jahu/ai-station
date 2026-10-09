import { useId } from "react";
import { useListKeyboard } from "./useListKeyboard";

export type RegistryToolCall = {
  id: string;
  tool: string;
  arguments?: Record<string, unknown>;
  round: number;
};

export function RegistryToolCalls({ calls }: { calls: RegistryToolCall[] }) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    calls,
    (call) => call.id,
  );
  if (!calls.length) return null;
  return (
    <section className="panel" aria-labelledby={headingId}>
      <h2 id={headingId}>Registry tool calls</h2>
      <p className="muted">
        Bounded calls from the typed agent registry. The model cannot invent
        tools, URLs, queries or shell commands.
      </p>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a registry call while the list is focused. There is no
        inspectable tool-call Run; results stay on this report.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {calls.map((call, i) => (
          <div
            key={call.id}
            aria-label={`Call ${call.tool} ${call.id}`}
            {...itemProps(i, call.id)}
          >
            <div>
              <strong>{call.tool}</strong>
              <p>
                round {call.round + 1} ·{" "}
                <span className="mono">{call.id.slice(0, 8)}</span>
              </p>
              <pre>{JSON.stringify(call.arguments ?? {}, null, 2)}</pre>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
