import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

type ListOptions = {
  disabled?: boolean;
  tabIndex?: number;
};

function isActive(tabIndex: number | undefined) {
  return (tabIndex ?? 0) >= 0;
}

function rowTab(active: boolean, current: boolean) {
  return active && current ? 0 : -1;
}

export function ApprovalChoiceList({
  checked,
  onChange,
  disabled = false,
  tabIndex,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
} & ListOptions) {
  const labelId = useId();
  const items = ["require_approval"] as const;
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    [...items],
    (item) => item,
  );
  const active = isActive(tabIndex);
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    event.preventDefault();
    if (disabled) return;
    onChange(!checked);
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose an approval policy while the list is focused. Space or
        Enter selects it. There is no inspectable approval-policy Run.
      </p>
      <div
        ref={listRef}
        className="agent-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        <div
          aria-label="Approval require_approval"
          {...itemProps(0, "require_approval")}
          tabIndex={rowTab(active, index === 0)}
        >
          <label className="agent-tool agent-wide">
            <input
              type="checkbox"
              checked={checked}
              disabled={disabled}
              tabIndex={rowTab(active, index === 0)}
              onChange={(event) => onChange(event.target.checked)}
            />
            <span>
              <strong>Require approval before each Run</strong>
              <small>
                Manual and scheduled executions park in waiting_for_approval.
                The worker does not start tools or inference until you grant the
                Run. Deny or cancel leaves no report.
              </small>
            </span>
          </label>
        </div>
      </div>
    </>
  );
}

export function RetryChoiceList({
  mode,
  onChange,
  disabled = false,
  tabIndex,
  name = "retry_policy",
}: {
  mode: "none" | "manual";
  onChange: (mode: "none" | "manual") => void;
  name?: string;
} & ListOptions) {
  const labelId = useId();
  const items = [
    {
      key: "none" as const,
      title: "No retry",
      detail: "Inspect the failed Runs. Start a new execution yourself.",
    },
    {
      key: "manual" as const,
      title: "Manual retry",
      detail:
        "After failure or interruption, the workflow inspector can queue a new Run with the same saved snapshot.",
    },
  ];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.key,
  );
  const active = isActive(tabIndex);
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    const item = items[index];
    if (!item) return;
    event.preventDefault();
    if (disabled) return;
    onChange(item.key);
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a retry policy while the list is focused. Space or
        Enter selects it. Manual retry never auto-loops. There is no inspectable
        retry-policy Run.
      </p>
      <div
        ref={listRef}
        className="agent-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Retry ${item.key}`}
              {...itemProps(i, item.key)}
              tabIndex={rowTab(active, current)}
            >
              <label className="agent-tool">
                <input
                  type="radio"
                  name={name}
                  checked={mode === item.key}
                  disabled={disabled}
                  tabIndex={rowTab(active, current)}
                  onChange={() => onChange(item.key)}
                />
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.detail}</small>
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}

export function ToolCallingChoiceList({
  mode,
  onChange,
  disabled = false,
  tabIndex,
}: {
  mode: "none" | "bounded";
  onChange: (mode: "none" | "bounded") => void;
} & ListOptions) {
  const labelId = useId();
  const items = ["bounded"] as const;
  const checked = mode === "bounded";
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    [...items],
    (item) => item,
  );
  const active = isActive(tabIndex);
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    event.preventDefault();
    if (disabled) return;
    onChange(checked ? "none" : "bounded");
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a tool-calling policy while the list is focused. Space
        or Enter selects it. Invented tools, URLs and commands fail closed.
        There is no inspectable tool-calling-policy Run.
      </p>
      <div
        ref={listRef}
        className="agent-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        <div
          aria-label="Tool calling bounded"
          {...itemProps(0, "bounded")}
          tabIndex={rowTab(active, index === 0)}
        >
          <label className="agent-tool">
            <input
              type="checkbox"
              checked={checked}
              disabled={disabled}
              tabIndex={rowTab(active, index === 0)}
              onChange={(event) =>
                onChange(event.target.checked ? "bounded" : "none")
              }
            />
            <span>
              <strong>Bounded tool calling during the report</strong>
              <small>
                The model may request selected operational tools from the typed
                registry. It cannot invent tools, URLs, search queries, shell
                commands or browser actions. Each call is an event plus a JSON
                artifact on the report Run. Existing agents stay off until you
                check this.
              </small>
            </span>
          </label>
        </div>
      </div>
    </>
  );
}

export function WorkflowModeChoiceList({
  mode,
  onChange,
  disabled = false,
  tabIndex,
  name = "workflow_mode",
}: {
  mode: "sequential" | "gated";
  onChange: (mode: "sequential" | "gated") => void;
  name?: string;
} & ListOptions) {
  const labelId = useId();
  const items = [
    {
      key: "sequential" as const,
      title: "Sequential",
      detail:
        "Context tools then the report. Each step waits for the previous one to succeed.",
    },
    {
      key: "gated" as const,
      title: "Gated",
      detail:
        "Same sequence, but the report waits in waiting_for_approval after context tools finish so you can inspect their artifacts first.",
    },
  ];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.key,
  );
  const active = isActive(tabIndex);
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    const item = items[index];
    if (!item) return;
    event.preventDefault();
    if (disabled) return;
    onChange(item.key);
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a workflow mode while the list is focused. Space or
        Enter selects it. The model cannot add tools, URLs or shell commands.
        There is no inspectable workflow-mode Run.
      </p>
      <div
        ref={listRef}
        className="agent-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Workflow ${item.key}`}
              {...itemProps(i, item.key)}
              tabIndex={rowTab(active, current)}
            >
              <label className="agent-tool">
                <input
                  type="radio"
                  name={name}
                  checked={mode === item.key}
                  disabled={disabled}
                  tabIndex={rowTab(active, current)}
                  onChange={() => onChange(item.key)}
                />
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.detail}</small>
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}

export function NoticeChoiceList({
  policy,
  onChange,
  disabled = false,
  tabIndex,
}: {
  policy: {
    on_success: boolean;
    on_failure: boolean;
    on_approval: boolean;
  };
  onChange: (policy: {
    on_success: boolean;
    on_failure: boolean;
    on_approval: boolean;
  }) => void;
} & ListOptions) {
  const labelId = useId();
  const items = [
    {
      key: "on_failure" as const,
      title: "When a workflow or report fails or is interrupted",
    },
    { key: "on_success" as const, title: "When a report succeeds" },
    {
      key: "on_approval" as const,
      title: "When a Run is waiting for approval",
    },
  ];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.key,
  );
  const active = isActive(tabIndex);
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    const item = items[index];
    if (!item) return;
    event.preventDefault();
    if (disabled) return;
    onChange({ ...policy, [item.key]: !policy[item.key] });
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a notice policy while the list is focused. Space or
        Enter selects it. Notices stay in AI Station. There is no inspectable
        notice-policy Run.
      </p>
      <div
        ref={listRef}
        className="agent-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Notice ${item.key}`}
              {...itemProps(i, item.key)}
              tabIndex={rowTab(active, current)}
            >
              <label className="agent-tool">
                <input
                  type="checkbox"
                  checked={policy[item.key]}
                  disabled={disabled}
                  tabIndex={rowTab(active, current)}
                  onChange={(event) =>
                    onChange({ ...policy, [item.key]: event.target.checked })
                  }
                />
                <span>
                  <strong>{item.title}</strong>
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}
