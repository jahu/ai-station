import { useId, type KeyboardEvent, type ReactNode } from "react";
import { useListKeyboard } from "./useListKeyboard";

export function ReviewChoiceList({
  checked,
  onChange,
  children,
  disabled,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = ["commit"] as const;
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    [...items],
    (item) => item,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    if (disabled) return;
    event.preventDefault();
    onChange(!checked);
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose the review acknowledgement while the list is focused.
        Space or Enter selects it. Enter does not queue a commit. There is no
        inspectable review-ack Run.
      </p>
      <div
        ref={listRef}
        className="review-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        <div aria-label="Review commit" {...itemProps(0, "commit")}>
          <label className="project-checkbox">
            <input
              type="checkbox"
              checked={checked}
              disabled={disabled}
              tabIndex={index === 0 ? 0 : -1}
              onChange={(event) => onChange(event.target.checked)}
            />
            {children}
          </label>
        </div>
      </div>
    </>
  );
}
