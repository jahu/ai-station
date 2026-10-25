import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";
import type { GpuChoice } from "./GpuChoiceList";

export function GpuTargetChoiceList({
  gpus,
  value,
  onChange,
  disabled,
  hint,
}: {
  gpus: GpuChoice[];
  value: string;
  onChange: (gpu: string) => void;
  disabled?: boolean;
  hint?: string;
}) {
  const labelId = useId();
  const items = [
    { key: "auto", title: "Auto · next available GPU", detail: "" },
    ...gpus.map((gpu) => ({
      key: String(gpu.index),
      title: `GPU ${gpu.index}${gpu.name ? ` · ${gpu.name}` : ""}`,
      detail: "",
    })),
  ];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.key,
    { initialKey: value },
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, summary, select")) return;
    if (event.key === " " && target.closest("input")) return;
    const item = items[index];
    if (!item || disabled) return;
    event.preventDefault();
    onChange(item.key);
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        {hint ??
          "Arrow keys choose a GPU target while the list is focused. Space or Enter selects it. Enter does not queue a Run. There is no inspectable GPU-target Run."}
      </p>
      <div
        ref={listRef}
        className="gpu-target-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Target GPU ${item.key}`}
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
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}
