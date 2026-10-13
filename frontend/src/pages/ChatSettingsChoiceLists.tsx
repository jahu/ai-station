import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";
import type { ChatProviderInfo } from "./ChatProviders";

export type SavedChatMode = "local" | "orchestrator";

const MODES = [
  {
    key: "orchestrator" as const,
    title: "Platform assistant",
    detail:
      "Saved for later turns. This conversation can route to owned actions.",
  },
  {
    key: "local" as const,
    title: "Conversation only",
    detail: "Saved for later turns. Replies stay in this conversation.",
  },
];

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

export function ConversationModeChoiceList({
  value,
  onChange,
  disabled,
}: {
  value: SavedChatMode;
  onChange: (mode: SavedChatMode) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [...MODES];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.key,
    { initialKey: value },
  );
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Let the assistant operate AI Station, or keep this conversation for
        answers.
      </p>
      <div
        ref={listRef}
        className="conversation-mode-choice-list"
        aria-labelledby={labelId}
        onKeyDown={(event) =>
          handleChoiceKey(
            event,
            onKeyDown,
            () => {
              const item = items[index];
              if (item) onChange(item.key);
            },
            disabled,
          )
        }
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Mode ${item.key}`}
              {...itemProps(i, item.key)}
            >
              <label className="agent-tool">
                <input
                  type="radio"
                  name={labelId}
                  checked={value === item.key}
                  disabled={disabled}
                  tabIndex={current ? 0 : -1}
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

export function ConversationProviderChoiceList({
  value,
  providers,
  onChange,
  disabled,
}: {
  value: string;
  providers: ChatProviderInfo[];
  onChange: (key: string) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = providers.map((row) => ({
    key: row.key,
    title: row.name,
    detail: `${row.location}${row.enabled ? "" : " · unavailable"}`,
    enabled: row.enabled,
  }));
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.key,
    { initialKey: value },
  );
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Choose where this conversation runs. External providers send messages
        outside your workstation.
      </p>
      <div
        ref={listRef}
        className="conversation-provider-choice-list"
        aria-labelledby={labelId}
        onKeyDown={(event) =>
          handleChoiceKey(
            event,
            onKeyDown,
            () => {
              const item = items[index];
              if (item?.enabled) onChange(item.key);
            },
            disabled,
          )
        }
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Provider ${item.key}`}
              {...itemProps(i, item.key)}
            >
              <label className="agent-tool">
                <input
                  type="radio"
                  name={labelId}
                  checked={value === item.key}
                  disabled={disabled || !item.enabled}
                  tabIndex={current ? 0 : -1}
                  onChange={() => {
                    if (item.enabled) onChange(item.key);
                  }}
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
