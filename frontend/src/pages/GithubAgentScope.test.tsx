import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import GithubAgentScope from "./GithubAgentScope";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function show(
  value: Parameters<typeof GithubAgentScope>[0]["value"],
  onChange = vi.fn(),
) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <GithubAgentScope value={value} disabled={false} onChange={onChange} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onChange;
}
function repository() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          id: "repo-id",
          kind: "github",
          name: "Our project",
          enabled: true,
          repository: "owner/repo",
        },
      ],
    })),
  );
}

it("chooses reviewed target metadata without running or enabling the agent", async () => {
  repository();
  const save = show(null);
  await screen.findByRole("option", { name: "Our project · owner/repo" });
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(
    screen.getByRole("combobox", { name: "Reviewed GitHub repository" }),
    { target: { value: "repo-id" } },
  );
  expect(save).toHaveBeenCalledWith({
    connector_id: "repo-id",
    repository: "owner/repo",
  });
});
it("keeps changed target visible and never silently follows the connector", async () => {
  repository();
  const save = show({ connector_id: "repo-id", repository: "previous/repo" });
  await screen.findByText(
    /reviewed target previous\/repo is unavailable or changed/,
  );
  expect(
    (
      screen.getByRole("combobox", {
        name: "Reviewed GitHub repository",
      }) as HTMLSelectElement
    ).value,
  ).toBe("");
  expect(save).not.toHaveBeenCalled();
});

it("displays the complete saved repository outside the compact select", async () => {
  repository();
  show({ connector_id: "repo-id", repository: "owner/repo" });
  await screen.findByRole("option", { name: "Our project · owner/repo" });
  expect(screen.getByLabelText("Reviewed repository name").textContent).toBe(
    "owner/repo",
  );
});
