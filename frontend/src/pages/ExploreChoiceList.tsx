import { useId, type KeyboardEvent, type ReactNode } from "react";
import { useListKeyboard } from "./useListKeyboard";

export function ExploreChoiceList({
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
  const items = ["automatic"] as const;
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
        Arrow keys choose automatic file discovery while the list is focused.
        Space or Enter selects it. Enter does not start a coding Run. There is
        no inspectable exploration-policy Run.
      </p>
      <div
        ref={listRef}
        className="explore-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        <div aria-label="Explore automatic" {...itemProps(0, "automatic")}>
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
