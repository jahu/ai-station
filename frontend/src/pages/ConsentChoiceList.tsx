import { useId, type KeyboardEvent, type ReactNode } from "react";
import { useListKeyboard } from "./useListKeyboard";

export function ConsentChoiceList({
  checked,
  onChange,
  children,
  required,
  disabled,
  labelClassName = "project-checkbox",
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  required?: boolean;
  disabled?: boolean;
  labelClassName?: string;
}) {
  const labelId = useId();
  const items = ["external_ai"] as const;
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
        Arrow keys choose the consent toggle while the list is focused. Space or
        Enter selects it. Enter does not start a coding Run. There is no
        inspectable consent Run.
      </p>
      <div
        ref={listRef}
        className="consent-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        <div
          aria-label="Consent external_ai"
          {...itemProps(0, "external_ai")}
        >
          <label className={labelClassName}>
            <input
              type="checkbox"
              checked={checked}
              required={required}
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
