import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FetchedPages } from "./AgentHttpFetch";

afterEach(() => cleanup());

it("shows fetched page cards without rendering page HTML", () => {
  render(
    <FetchedPages
      result={{
        urls: ["https://www.example.com/"],
        fetched_at: "2026-10-09T08:00:00Z",
        pages: [
          {
            url: "https://www.example.com/",
            status: 200,
            text: "<script>alert(1)</script>Public excerpt",
            untrusted: true,
          },
        ],
      }}
    />,
  );
  expect(
    screen.getByRole("link", { name: /www.example.com/ }).getAttribute("href"),
  ).toBe("https://www.example.com/");
  expect(screen.getByText("HTML/text excerpt stored")).toBeTruthy();
  expect(screen.queryByText("Public excerpt")).toBeNull();
  expect(document.querySelector("script")).toBeNull();
});

it("moves through fetched pages with arrow keys", () => {
  render(
    <FetchedPages
      result={{
        urls: ["https://www.example.com/", "https://www.example.org/status"],
        fetched_at: "2026-10-09T08:00:00Z",
        pages: [
          {
            url: "https://www.example.com/",
            status: 200,
            text: "Public excerpt",
            untrusted: true,
          },
          {
            url: "https://www.example.org/status",
            status: 200,
            skipped: "binary",
          },
        ],
      }}
    />,
  );
  const first = screen.getByRole("link", {
    name: "Page https://www.example.com/",
  });
  const second = screen.getByRole("link", {
    name: "Page https://www.example.org/status",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Fetched pages" })).toBeTruthy();
  expect(screen.getByText(/Arrow keys choose a page/)).toBeTruthy();
  expect(first.getAttribute("rel")).toContain("noreferrer");
  fireEvent.keyDown(first.closest(".web-source-grid") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".web-source-grid") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
