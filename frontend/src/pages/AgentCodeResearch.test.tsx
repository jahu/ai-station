import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Run } from "../api";
import AgentCodeResearch from "./AgentCodeResearch";

afterEach(cleanup);
function rows() {
  const scope = {
    task_id: "task",
    agent_id: "agent",
    project_id: "project",
    parent_run_id: "workflow",
    status: "succeeded",
  };
  return [
    {
      ...scope,
      id: "handoff",
      executor_type: "agent_page_coding",
      parameters: { source_run_ids: ["search", "pages"] },
    },
    {
      ...scope,
      id: "search",
      executor_type: "agent_tool",
      parameters: { tool: "web_search" },
      metadata: {
        web_search: {
          query: "public notes",
          searched_at: "2026-10-24T12:00:00Z",
          partial: false,
          sources: [
            {
              id: 1,
              url: "https://example.com/",
              title: "Reference",
              snippet: "Snippet only",
            },
          ],
        },
      },
    },
    {
      ...scope,
      id: "pages",
      executor_type: "agent_tool",
      parameters: { tool: "search_pages" },
      metadata: {
        search_pages: {
          query: "public notes",
          fetched_at: "2026-10-24T12:00:00Z",
          search_artifact_id: "snapshot",
          partial: true,
          urls: ["https://example.com/", "https://missing.example.com/"],
          pages: [
            { url: "https://example.com/", text: "Actually opened source" },
          ],
          errors: [
            { url: "https://missing.example.com/", error: "Unavailable" },
          ],
        },
      },
    },
  ] as unknown as Run[];
}
it("shows compact task-bound research with explicit partial reading and snapshot links", () => {
  render(
    <MemoryRouter>
      <AgentCodeResearch runs={rows()} taskId="task" />
    </MemoryRouter>,
  );
  const details = screen.getByLabelText("Research for this task");
  expect(details.hasAttribute("open")).toBe(false);
  fireEvent.click(
    screen.getByText("Research sources · Some pages unavailable"),
  );
  expect(
    screen
      .getByRole("link", { name: "Source Reference 1" })
      .getAttribute("href"),
  ).toBe("https://example.com/");
  expect(
    screen
      .getByRole("link", { name: "Page https://example.com/" })
      .getAttribute("href"),
  ).toBe("https://example.com/");
  expect(screen.getByRole("status").textContent).toMatch(/could not be read/);
  expect(
    screen.getByRole("link", { name: "Search snapshot" }).getAttribute("href"),
  ).toBe("/library/snapshot");
});
it("does not show another task's or unpublished source observations", () => {
  const runs = rows();
  runs[0].parameters = { source_run_ids: ["different-source"] };
  const view = render(
    <MemoryRouter>
      <AgentCodeResearch runs={runs} taskId="task" />
    </MemoryRouter>,
  );
  expect(screen.queryByLabelText("Research for this task")).toBeNull();
  view.rerender(
    <MemoryRouter>
      <AgentCodeResearch runs={rows()} taskId="other-task" />
    </MemoryRouter>,
  );
  expect(screen.queryByLabelText("Research for this task")).toBeNull();
});
