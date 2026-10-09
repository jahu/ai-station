import { useRef, useState, type KeyboardEvent } from "react";

export type ListKeyboardOptions = {
  initialKey?: string;
  fallback?: "first" | "last";
};

export function useListKeyboard<T, E extends HTMLElement = HTMLDivElement>(
  items: T[],
  getKey: (item: T) => string,
  options?: ListKeyboardOptions,
) {
  const listRef = useRef<E>(null);
  const [selectedKey, setSelectedKey] = useState(
    options?.initialKey || (items[0] ? getKey(items[0]) : ""),
  );
  const found = items.findIndex((item) => getKey(item) === selectedKey);
  const index =
    found >= 0
      ? found
      : options?.fallback === "last"
        ? Math.max(0, items.length - 1)
        : 0;
  const focusItem = (next: number) => {
    const clamped = Math.max(0, Math.min(items.length - 1, next));
    const item = items[clamped];
    if (!item) return;
    setSelectedKey(getKey(item));
    const target = listRef.current?.querySelector<HTMLElement>(
      `[data-list-index="${clamped}"]`,
    );
    target?.focus();
    target?.scrollIntoView?.({ block: "nearest" });
  };
  const onKeyDown = (event: KeyboardEvent<E>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      event.preventDefault();
      focusItem(index + 1);
    } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      event.preventDefault();
      focusItem(index - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusItem(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusItem(items.length - 1);
    }
  };
  const itemProps = (i: number, key: string) => ({
    "aria-current": (i === index ? "true" : undefined) as "true" | undefined,
    tabIndex: i === index ? 0 : -1,
    "data-list-index": i,
    onFocus: () => setSelectedKey(key),
  });
  return { listRef, index, selectedKey, setSelectedKey, onKeyDown, itemProps };
}
