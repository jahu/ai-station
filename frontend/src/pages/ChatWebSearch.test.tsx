import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { SearchSources, WebSearchControl } from "./ChatWebSearch";

afterEach(cleanup);

it("starts offline and exposes a bounded explicit query only when enabled", () => {
  function Control() {
    const [enabled, setEnabled] = useState(false);
    const [query, setQuery] = useState("");
    return (
      <WebSearchControl
        enabled={enabled}
        query={query}
        busy={false}
        onToggle={setEnabled}
        onQuery={setQuery}
      />
    );
  }
  render(<Control />);
  expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false");
  expect(screen.queryByLabelText("Search query")).toBeNull();
  fireEvent.click(screen.getByRole("switch"));
  fireEvent.change(screen.getByLabelText("Search query"), {
    target: { value: "llama.cpp releases" },
  });
  expect(
    (screen.getByLabelText("Search query") as HTMLInputElement).value,
  ).toBe("llama.cpp releases");
  expect(screen.getByLabelText("Search query").getAttribute("maxlength")).toBe(
    "500",
  );
  expect(
    screen.getByText(/Conversation history and attachments stay local/),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("switch"));
  expect(screen.queryByLabelText("Search query")).toBeNull();
});

it("shows actual source links and partial results independently of the model answer", () => {
  render(
    <SearchSources
      result={{
        query: "llama.cpp",
        searched_at: "2026-09-29T00:00:00Z",
        partial: true,
        sources: [
          {
            id: 1,
            title: "Official repository",
            url: "https://github.com/ggml-org/llama.cpp",
            snippet: "Untrusted source text",
          },
        ],
      }}
    />,
  );
  const link = screen.getByRole("link", { name: /Official repository/ });
  expect(link.getAttribute("href")).toBe(
    "https://github.com/ggml-org/llama.cpp",
  );
  expect(link.getAttribute("rel")).toContain("noreferrer");
  expect(screen.getByText(/Some search engines did not respond/)).toBeTruthy();
});

it("moves through search sources with arrow keys", () => {
  render(
    <SearchSources
      result={{
        query: "llama.cpp",
        searched_at: "2026-09-29T00:00:00Z",
        partial: false,
        sources: [
          {
            id: 1,
            title: "Official repository",
            url: "https://github.com/ggml-org/llama.cpp",
            snippet: "Untrusted source text",
          },
          {
            id: 2,
            title: "Server docs",
            url: "https://github.com/ggml-org/llama.cpp/blob/master/README.md",
            snippet: "More untrusted text",
          },
        ],
      }}
    />,
  );
  const first = screen.getByRole("link", {
    name: "Source Official repository 1",
  });
  const second = screen.getByRole("link", { name: "Source Server docs 2" });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Search sources" })).toBeTruthy();
  expect(
    screen.getByText(/This is search, not browser automation/),
  ).toBeTruthy();
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
