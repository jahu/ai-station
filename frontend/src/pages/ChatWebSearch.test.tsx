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
    screen.getByText(/full conversation and attachments are not sent/),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("switch"));
  expect(screen.queryByLabelText("Search query")).toBeNull();
});

it("moves through the search toggle without sending a message", () => {
  function Control() {
    const [enabled, setEnabled] = useState(false);
    return (
      <WebSearchControl
        enabled={enabled}
        query=""
        busy={false}
        onToggle={setEnabled}
        onQuery={() => undefined}
      />
    );
  }
  render(<Control />);
  const toggle = screen.getByLabelText("Search web_search");
  expect(toggle.tabIndex).toBe(0);
  expect(screen.getByText(/Attachments and memory are excluded/)).toBeTruthy();
  expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false");
  fireEvent.keyDown(toggle.closest(".web-search-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("true");
  const describedBy = screen
    .getByRole("switch")
    .getAttribute("aria-describedby");
  expect(document.getElementById(describedBy ?? "")?.textContent).toContain(
    "installed local Vision model",
  );
  expect(screen.getByLabelText("Search query")).toBeTruthy();
  fireEvent.keyDown(toggle.closest(".web-search-choice-list") as HTMLElement, {
    key: " ",
  });
  expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false");
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

it("shows the actual locally prepared query alongside the user's original question", () => {
  render(
    <SearchSources
      result={{
        query: "Breaking Bad actor death report fact check",
        original_query: "A question about an actor",
        query_preparation: { location: "local", model: "local-fixture" },
        searched_at: "2026-10-30T00:00:00Z",
        partial: false,
        sources: [],
      }}
    />,
  );
  expect(
    screen.getByText(/Searched: Breaking Bad actor death report fact check/),
  ).toBeTruthy();
  expect(screen.getByText("Question: A question about an actor")).toBeTruthy();
  expect(
    screen.getByText("Query prepared locally · local-fixture"),
  ).toBeTruthy();
});

it("labels preparation by an explicitly selected external model", () => {
  render(
    <SearchSources
      result={{
        query: "public query",
        query_preparation: {
          location: "external",
          model: "chosen-cloud-model",
        },
        searched_at: "2026-10-30T00:00:00Z",
        partial: false,
        sources: [],
      }}
    />,
  );
  expect(
    screen.getByText(
      "Query prepared with selected external model · chosen-cloud-model",
    ),
  ).toBeTruthy();
  expect(screen.queryByText(/Query prepared locally/)).toBeNull();
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

it("keeps the default online composer compact while exposing exact-query options", () => {
  render(
    <WebSearchControl
      compact
      enabled
      query=""
      busy={false}
      onToggle={() => {}}
      onQuery={() => {}}
    />,
  );
  expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("true");
  expect(screen.queryByLabelText("Search query")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Search options" }));
  expect(screen.getByLabelText("Search query")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Search options" }));
  expect(screen.queryByLabelText("Search query")).toBeNull();
});

it("requires an explicit rendering choice and clears it for exact search queries", () => {
  function Control() {
    const [query, setQuery] = useState("");
    const [renderPages, setRenderPages] = useState(false);
    return (
      <WebSearchControl
        compact
        enabled
        query={query}
        busy={false}
        onToggle={() => {}}
        onQuery={setQuery}
        renderPages={renderPages}
        onRenderPages={setRenderPages}
      />
    );
  }
  render(<Control />);
  expect(
    screen.queryByRole("checkbox", { name: "Read JavaScript pages" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Search options" }));
  const checkbox = screen.getByRole("checkbox", {
    name: "Read JavaScript pages",
  }) as HTMLInputElement;
  expect(checkbox.checked).toBe(false);
  fireEvent.click(checkbox);
  expect(checkbox.checked).toBe(true);
  expect(screen.getByText(/installed local Vision model/)).toBeTruthy();
  expect(
    screen.getByText(/For this message: include a public page URL/),
  ).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Search query"), {
    target: { value: "public topic" },
  });
  expect(checkbox.checked).toBe(false);
  expect(checkbox.disabled).toBe(true);
});
