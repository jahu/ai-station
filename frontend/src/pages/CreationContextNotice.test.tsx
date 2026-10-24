import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import CreationContextNotice from "./CreationContextNotice";

afterEach(cleanup);

it("lets the user inspect the exact plain earlier text supplied for creation", () => {
  render(
    <CreationContextNotice
      value={{
        messages: [
          { role: "user", content: "Use numbers 5, 8, 13", truncated: false },
          {
            role: "assistant",
            content: "Label: Fibonacci sample",
            truncated: false,
          },
        ],
        older_messages_omitted: false,
      }}
    />,
  );
  expect(screen.getByText("Using 2 earlier messages")).toBeTruthy();
  expect(screen.getByText("Use numbers 5, 8, 13")).toBeTruthy();
  expect(screen.getByText("Label: Fibonacci sample")).toBeTruthy();
  const details = screen.getByLabelText(
    "Conversation context used for file creation",
  );
  expect(details.hasAttribute("open")).toBe(false);
  expect(screen.queryByText(/Limited context/)).toBeNull();
});

it("labels missing older or truncated text and renders it without active HTML or remote sources", () => {
  const { container } = render(
    <CreationContextNotice
      value={{
        messages: [
          {
            role: "user",
            content: '<img src="https://example.com/private">',
            truncated: true,
          },
        ],
        older_messages_omitted: true,
      }}
    />,
  );
  expect(
    screen.getByText(/Using 1 earlier message · Limited context/),
  ).toBeTruthy();
  expect(screen.getByText("Excerpt only")).toBeTruthy();
  expect(screen.getByText(/Some earlier text is omitted/)).toBeTruthy();
  expect(container.querySelector("img,a,iframe")).toBeNull();
});

it("leaves legacy messages unchanged when no creation context was supplied", () => {
  const { container } = render(<CreationContextNotice />);
  expect(container.innerHTML).toBe("");
});
