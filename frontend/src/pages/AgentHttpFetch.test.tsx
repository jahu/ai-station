import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
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
  expect(screen.getByRole("link", { name: /www.example.com/ }).getAttribute("href")).toBe(
    "https://www.example.com/",
  );
  expect(screen.getByText("HTML/text excerpt stored")).toBeTruthy();
  expect(screen.queryByText("Public excerpt")).toBeNull();
  expect(document.querySelector("script")).toBeNull();
});
