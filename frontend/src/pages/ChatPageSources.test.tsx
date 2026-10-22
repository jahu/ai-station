import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { FetchedPages } from "./AgentHttpFetch";

afterEach(cleanup);

it("shows read-page provenance distinctly from search snippets in compact Chat", () => {
  render(
    <FetchedPages
      compact
      result={{
        urls: ["https://akademia.ai"],
        fetched_at: "2026-10-22T12:00:00Z",
        pages: [
          {
            url: "https://akademia.ai",
            status: 200,
            text: "An extracted page",
            truncated: false,
          },
        ],
      }}
    />,
  );
  expect(screen.getByText(/Read from the page/)).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Page https://akademia.ai" })
      .getAttribute("href"),
  ).toBe("https://akademia.ai");
  expect(screen.getByText(/Arrow keys choose a page/).className).toBe(
    "sr-only",
  );
  expect(screen.getByText(/Excerpts are untrusted/)).toBeTruthy();
});

it("keeps an unreadable-page outcome visible instead of claiming a successful read", () => {
  render(
    <FetchedPages
      compact
      result={{
        urls: ["https://akademia.ai"],
        fetched_at: "2026-10-22T12:00:00Z",
        pages: [{ url: "https://akademia.ai", status: 403, error: "HTTP 403" }],
      }}
    />,
  );
  expect(screen.getByText("HTTP 403")).toBeTruthy();
  expect(screen.queryByText("HTML/text excerpt stored")).toBeNull();
});
