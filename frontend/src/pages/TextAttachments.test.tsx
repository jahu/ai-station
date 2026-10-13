import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import TextAttachments, { type TextAttachment } from "./TextAttachments";

afterEach(cleanup);
function Composer() {
  const [items, setItems] = useState<TextAttachment[]>([]);
  const [reading, setReading] = useState(false);
  return (
    <>
      <TextAttachments
        attachments={items}
        onChange={setItems}
        busy={reading}
        onReading={setReading}
      />
      <button disabled={reading}>Send</button>
    </>
  );
}
function file(name: string, bytes: Uint8Array) {
  const value = new File([new ArrayBuffer(bytes.length)], name);
  Object.defineProperty(value, "arrayBuffer", {
    value: async () => bytes.buffer,
  });
  return value;
}
it("previews selected text and supports removing it before sending", async () => {
  render(<Composer />);
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: {
      files: [file("code.py", new TextEncoder().encode("print(42)\n"))],
    },
  });
  expect(screen.getByRole("button", { name: "Send" })).toHaveProperty(
    "disabled",
    true,
  );
  await screen.findByText("print(42)");
  expect(screen.getByRole("button", { name: "Send" })).toHaveProperty(
    "disabled",
    false,
  );
  fireEvent.click(screen.getByRole("button", { name: "Remove code.py" }));
  expect(screen.queryByText("print(42)")).toBeNull();
});
it("rejects binary and oversized files without adding them", async () => {
  render(<Composer />);
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: { files: [file("bad.bin", new Uint8Array([0]))] },
  });
  await screen.findByText("bad.bin is not a supported text file.");
  expect(screen.queryByRole("button", { name: "Remove bad.bin" })).toBeNull();
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: { files: [file("large.txt", new Uint8Array(16001))] },
  });
  await screen.findByText("large.txt exceeds 16 KB.");
});
it("stages a PDF and image without treating them as UTF-8 text", async () => {
  render(<Composer />);
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: {
      files: [file("notes.pdf", new Uint8Array([0x25, 0x50, 0x44, 0x46]))],
    },
  });
  await screen.findByText("PDF · text will be extracted when you send");
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: {
      files: [file("photo.png", new Uint8Array([0x89, 0x50, 0x4e, 0x47]))],
    },
  });
  await screen.findByText(/Pixels are not sent to the model/);
  expect(screen.getByRole("img", { name: "photo.png" })).toBeTruthy();
});
it("moves through staged text attachments with arrow keys without sending", async () => {
  render(<Composer />);
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: {
      files: [
        file("code.py", new TextEncoder().encode("print(1)\n")),
        file("notes.md", new TextEncoder().encode("# notes\n")),
      ],
    },
  });
  const first = await screen.findByLabelText("Attachment code.py");
  const second = screen.getByLabelText("Attachment notes.md");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable attachment Run/),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".chat-attachment-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement).toBe(second);
  expect(screen.getByRole("button", { name: "Remove notes.md" }).tabIndex).toBe(
    0,
  );
  fireEvent.keyDown(second.closest(".chat-attachment-list") as HTMLElement, {
    key: "Enter",
  });
  expect(screen.getByLabelText("Attachment notes.md")).toBeTruthy();
  fireEvent.keyDown(second.closest(".chat-attachment-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
