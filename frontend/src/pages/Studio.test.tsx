import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Studio, StudioProject } from "./Studio";
import {
  initialDefinition,
  type CreativeProject,
} from "../components/creative/creative-project";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const base: CreativeProject = {
  ...initialDefinition(),
  id: "project-one",
  name: "Learning studio",
  description: "Stories about practical skills",
  aliases: ["example.org"],
  version: 1,
  created_at: "2026-11-11T10:00:00Z",
  updated_at: "2026-11-11T10:00:00Z",
  archived_at: null,
};

function fixture(
  path: string,
  options: { empty?: boolean; conflict?: boolean } = {},
) {
  let project = structuredClone(base);
  const mutations: {
    path: string;
    method: string;
    body: Record<string, unknown>;
  }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const response = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        });
      if (!init?.method || init.method === "GET") {
        if (url.pathname === "/api/creative/projects")
          return response(
            options.empty
              ? []
              : url.searchParams.get("archived") === "true"
                ? project.archived_at
                  ? [project]
                  : []
                : project.archived_at
                  ? []
                  : [project],
          );
        if (url.pathname === "/api/creative/projects/project-one")
          return response(project);
        if (
          url.pathname === "/api/creative/sessions" ||
          url.pathname === "/api/studio/materials"
        )
          return response([]);
      }
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<
        string,
        unknown
      >;
      mutations.push({
        path: url.pathname,
        method: init?.method ?? "GET",
        body,
      });
      if (options.conflict && init?.method === "PUT")
        return response(
          { detail: "This creative project changed. Reload before saving." },
          409,
        );
      if (url.pathname.endsWith("/archive")) {
        project = {
          ...project,
          archived_at: body.archived ? "2026-11-11T11:00:00Z" : null,
          version: project.version + 1,
        };
        return response(project);
      }
      project = {
        ...project,
        ...body,
        version: init?.method === "POST" ? 1 : project.version + 1,
      } as CreativeProject;
      return response(project, init?.method === "POST" ? 201 : 200);
    }),
  );
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/studio" element={<Studio />} />
          <Route path="/studio/new" element={<StudioProject create />} />
          <Route path="/studio/:id" element={<StudioProject />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { mutations };
}

it("creates a project with just a name, then opens its identity without running a workload", async () => {
  const { mutations } = fixture("/studio/new");
  fireEvent.change(screen.getByLabelText("Project name"), {
    target: { value: "A new course" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create project" }));
  await screen.findByRole("heading", { name: "A new course", level: 1 });
  expect(mutations).toHaveLength(1);
  expect(mutations[0]).toMatchObject({
    path: "/api/creative/projects",
    method: "POST",
    body: {
      name: "A new course",
      defaults: { format: "reel", audio: "voice_music" },
    },
  });
  expect(
    screen.getByRole("link", { name: "Create an image" }).getAttribute("href"),
  ).toContain("project=project-one");
});

it("shows recognizable project cards and makes archived projects accessible", async () => {
  fixture("/studio");
  const card = await screen.findByRole("link", { name: /Learning studio/ });
  expect(card.getAttribute("href")).toBe("/studio/project-one");
  fireEvent.click(screen.getByRole("button", { name: "Archived" }));
  await screen.findByRole("heading", {
    name: "Your archived projects will stay here",
  });
});

it("saves the complete identity with an optimistic version and confirms the save", async () => {
  const { mutations } = fixture("/studio/project-one");
  await screen.findByLabelText("Tone");
  fireEvent.change(screen.getByLabelText("Tone"), {
    target: { value: "Calm, specific and curious" },
  });
  fireEvent.change(screen.getByLabelText("Brand color 1"), {
    target: { value: "#336699" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save identity" }));
  await screen.findByText("Identity saved");
  expect(mutations).toHaveLength(1);
  expect(mutations[0]).toMatchObject({
    method: "PUT",
    body: {
      expected_version: 1,
      identity: {
        tone: "Calm, specific and curious",
        colors: ["#336699", "#101311", "#F7F8F4"],
      },
    },
  });
});

it("keeps the operator's edits visible when a concurrent save conflicts", async () => {
  fixture("/studio/project-one", { conflict: true });
  await screen.findByLabelText("Tone");
  fireEvent.change(screen.getByLabelText("Tone"), {
    target: { value: "My unsaved direction" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save identity" }));
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Reload before saving",
  );
  expect((screen.getByLabelText("Tone") as HTMLInputElement).value).toBe(
    "My unsaved direction",
  );
});

it("archives without deletion and can restore the same identity", async () => {
  const { mutations } = fixture("/studio/project-one");
  fireEvent.click(await screen.findByRole("button", { name: "Archive" }));
  await screen.findByRole("button", { name: "Restore project" });
  expect(screen.getByLabelText("Project name").matches(":disabled")).toBe(true);
  expect(screen.queryByRole("button", { name: "Save identity" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Restore project" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save identity" })).toBeTruthy(),
  );
  expect(mutations.map((m) => m.body)).toEqual([
    { expected_version: 1, archived: true },
    { expected_version: 2, archived: false },
  ]);
});

it("offers an intentional empty state with a direct project creation action", async () => {
  fixture("/studio", { empty: true });
  await screen.findByRole("heading", {
    name: "Start with a world of your own",
  });
  expect(
    screen
      .getByRole("link", { name: "Create your first project" })
      .getAttribute("href"),
  ).toBe("/studio/new");
});
