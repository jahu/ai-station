import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

export type AssistantRunChoice = { id: string; title: string; detail: string };

function handleChoiceKey(
  event: KeyboardEvent<HTMLDivElement>,
  onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void,
  select: () => void,
  disabled?: boolean,
) {
  onKeyDown(event);
  if (event.defaultPrevented) return;
  if (event.key !== " " && event.key !== "Enter") return;
  const target = event.target as HTMLElement;
  if (target.closest("a, button, textarea, summary, select")) return;
  if (event.key === " " && target.closest("input")) return;
  if (disabled) return;
  event.preventDefault();
  select();
}

function RunChoiceList({
  items,
  value,
  onChange,
  disabled,
  kind,
  note,
  className,
}: {
  items: AssistantRunChoice[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  kind: "Proposal" | "Commit";
  note: string;
  className: string;
}) {
  const labelId = useId();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.id,
    { initialKey: value },
  );
  if (!items.length) return null;
  return (
    <>
      <p id={labelId} className="dashboard-note">
        {note}
      </p>
      <div
        ref={listRef}
        className={className}
        aria-labelledby={labelId}
        onKeyDown={(event) =>
          handleChoiceKey(
            event,
            onKeyDown,
            () => {
              const item = items[index];
              if (item) onChange(item.id);
            },
            disabled,
          )
        }
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.id}
              aria-label={`${kind} ${item.id}`}
              {...itemProps(i, item.id)}
            >
              <label className="agent-tool">
                <input
                  type="radio"
                  name={labelId}
                  checked={value === item.id}
                  disabled={disabled}
                  tabIndex={current ? 0 : -1}
                  onChange={() => onChange(item.id)}
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

export function ProposalChoiceList({
  proposals,
  value,
  onChange,
  disabled,
}: {
  proposals: AssistantRunChoice[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  return (
    <RunChoiceList
      items={proposals}
      value={value}
      onChange={onChange}
      disabled={disabled}
      kind="Proposal"
      className="proposal-choice-list"
      note="Arrow keys choose a reviewed coding proposal from this conversation while the list is focused. Space or Enter selects it. Enter does not send or queue a commit. There is no inspectable proposal-selection Run."
    />
  );
}

export function CommitChoiceList({
  commits,
  value,
  onChange,
  disabled,
}: {
  commits: AssistantRunChoice[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  return (
    <RunChoiceList
      items={commits}
      value={value}
      onChange={onChange}
      disabled={disabled}
      kind="Commit"
      className="commit-choice-list"
      note="Arrow keys choose a successful reviewed commit from this conversation while the list is focused. Space or Enter selects it. Enter does not send or publish. There is no inspectable commit-selection Run."
    />
  );
}
