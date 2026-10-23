import { afterEach, expect, it, vi } from "vitest";
import { copyText } from "./clipboard";

const commandDescriptor = Object.getOwnPropertyDescriptor(
  document,
  "execCommand",
);
afterEach(() => {
  vi.unstubAllGlobals();
  if (commandDescriptor)
    Object.defineProperty(document, "execCommand", commandDescriptor);
  else delete (document as Partial<Document>).execCommand;
  document.getSelection()?.removeAllRanges();
  document.body.replaceChildren();
});

it("uses the native clipboard when available", async () => {
  const writeText = vi.fn(async () => {});
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  await copyText("A real answer");
  expect(writeText).toHaveBeenCalledWith("A real answer");
  expect(document.querySelector("textarea")).toBeNull();
});

it("copies selected plain text without Clipboard API and restores focus and selection", async () => {
  vi.stubGlobal("navigator", {});
  const button = document.createElement("button");
  button.textContent = "Copy";
  document.body.appendChild(button);
  button.focus();
  const selection = document.getSelection()!;
  const range = document.createRange();
  range.selectNodeContents(button);
  selection.removeAllRanges();
  selection.addRange(range);
  expect(selection.toString()).toBe("Copy");
  let copied = "";
  const command = vi.fn((action: string) => {
    expect(action).toBe("copy");
    const selected = document.activeElement as HTMLTextAreaElement;
    expect(selected.tagName).toBe("TEXTAREA");
    expect(selected.selectionEnd - selected.selectionStart).toBe(
      selected.value.length,
    );
    copied = selected.value;
    return true;
  });
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: command,
  });
  await copyText("<strong>literal text</strong>\nzażółć gęślą jaźń");
  expect(copied).toBe("<strong>literal text</strong>\nzażółć gęślą jaźń");
  expect(document.activeElement).toBe(button);
  expect(document.querySelector("textarea")).toBeNull();
  expect(selection.toString()).toBe("Copy");
});

it("reports failure and cleans temporary content when copying is denied", async () => {
  vi.stubGlobal("navigator", {
    clipboard: {
      writeText: vi.fn(async () => {
        throw new Error("Denied");
      }),
    },
  });
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: vi.fn(() => false),
  });
  await expect(copyText("Private text")).rejects.toThrow(
    "Clipboard unavailable",
  );
  expect(document.querySelector("textarea")).toBeNull();
});
