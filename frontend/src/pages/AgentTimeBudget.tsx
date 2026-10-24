import { useState } from "react";

export const MAX_AGENT_RUNTIME = 4 * 60 * 60;
const presets = [
  [600, "10 minutes"],
  [1800, "30 minutes"],
  [3600, "1 hour"],
  [7200, "2 hours"],
  [14400, "4 hours"],
] as const;

/** Keep the persisted seconds exact; choosing a preset is an explicit edit. */
export default function AgentTimeBudget({
  value,
  onChange,
  label = "Time limit",
  disabled,
  tabIndex,
}: {
  value: string | number;
  onChange: (seconds: string) => void;
  label?: string;
  disabled?: boolean;
  tabIndex?: number;
}) {
  const [custom, setCustom] = useState(
    !presets.some(([seconds]) => seconds === Number(value)),
  );
  return (
    <div
      className="agent-time-budget"
      onKeyDown={(event) => event.stopPropagation()}
    >
      <label>
        Time limit
        <select
          value={custom ? "custom" : String(value)}
          aria-label={label}
          disabled={disabled}
          tabIndex={tabIndex}
          onChange={(event) => {
            const selected = event.target.value;
            setCustom(selected === "custom");
            if (selected !== "custom") onChange(selected);
          }}
        >
          {presets.map(([seconds, text]) => (
            <option key={seconds} value={seconds}>
              {text}
            </option>
          ))}
          <option value="custom">Custom duration…</option>
        </select>
      </label>
      {custom ? (
        <label>
          Exact duration (seconds)
          <input
            type="number"
            required
            min={5}
            max={MAX_AGENT_RUNTIME}
            step={1}
            value={value}
            aria-label={`${label} seconds`}
            disabled={disabled}
            tabIndex={tabIndex}
            onChange={(event) => onChange(event.target.value)}
          />
        </label>
      ) : null}
      <p className="muted">
        Covers waiting for resources and every step of this run. Video and
        avatars can take longer to generate than their playback duration. Stop
        remains available throughout.
      </p>
    </div>
  );
}
