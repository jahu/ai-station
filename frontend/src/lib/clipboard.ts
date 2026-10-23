/** Copy from a user gesture, including private LAN HTTP without Clipboard API. */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // A denied native write may still allow the selection-based copy gesture.
    }
  }
  if (typeof document.execCommand !== "function") {
    throw new Error("Clipboard unavailable. Select and copy the text.");
  }
  const active = document.activeElement;
  const selection = document.getSelection();
  const range = selection?.rangeCount
    ? selection.getRangeAt(0).cloneRange()
    : null;
  const field = document.createElement("textarea");
  field.value = text;
  field.readOnly = true;
  field.setAttribute("aria-label", "Text being copied");
  Object.assign(field.style, {
    position: "fixed",
    top: "0",
    left: "0",
    opacity: "0",
    pointerEvents: "none",
  });
  document.body.appendChild(field);
  let copied = false;
  try {
    field.focus({ preventScroll: true });
    field.select();
    field.setSelectionRange(0, text.length);
    copied = document.execCommand("copy");
  } finally {
    field.remove();
    if (active instanceof HTMLElement) active.focus({ preventScroll: true });
    if (range && selection) {
      selection.removeAllRanges();
      selection.addRange(range);
    }
  }
  if (!copied)
    throw new Error("Clipboard unavailable. Select and copy the text.");
}
