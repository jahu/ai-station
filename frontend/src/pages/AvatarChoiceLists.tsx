import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

const QUALITIES = [
  { key: 256, title: "Draft · 256 px", detail: "Fastest local preview." },
  { key: 384, title: "Balanced · 384 px", detail: "Default EchoMimic area." },
  {
    key: 512,
    title: "Detailed · 512 px",
    detail: "Largest owned portrait size.",
  },
] as const;

const CLIPS = [17, 33, 49, 65, 81] as const;

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

export function AvatarQualityChoiceList({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (size: number) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [...QUALITIES];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => String(item.key),
    { initialKey: String(value) },
  );
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose Quality while the list is focused. Space or Enter
        selects it. Enter does not queue a Run. There is no inspectable quality
        Run.
      </p>
      <div
        ref={listRef}
        className="avatar-quality-choice-list"
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
              aria-label={`Quality ${item.key}`}
              {...itemProps(i, String(item.key))}
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

export function AvatarClipChoiceList({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (frames: number) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = CLIPS.map((frames) => ({
    key: frames,
    title: `Up to ${(frames / 25).toFixed(2)} seconds`,
    detail: `${frames} frames at 25 fps. Shorter audio still wins.`,
  }));
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => String(item.key),
    { initialKey: String(value) },
  );
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose Clip length while the list is focused. Space or Enter
        selects it. Enter does not queue a Run. There is no inspectable
        clip-length Run.
      </p>
      <div
        ref={listRef}
        className="avatar-clip-choice-list"
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
              aria-label={`Clip ${item.key}`}
              {...itemProps(i, String(item.key))}
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
